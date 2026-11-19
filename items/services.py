import logging
import uuid

from django.core.files.base import ContentFile
from django.db import transaction

from ai import images
from ai.services import AIError, analyze_item_image, embed_text, summarize_item
from common.storage import private_storage, public_storage
from matching.engine import FOUND, LOST, schedule_matching

from .models import FoundItem, ItemImage, LostItem

logger = logging.getLogger(__name__)

ORIGINAL_MAX_SIDE = 3000


class NoItemDetected(Exception):
    """AI가 사진에서 분실물로 볼 물건을 찾지 못함 (→ 422)."""


class AnalysisUnavailable(Exception):
    """AI 분석 실패·시간 초과 (→ 504)."""


def create_analyzed_image(user, upload):
    """
    사진 업로드 → AI 분석 → 블러 → 공개/비공개 저장 → ItemImage 생성.

    반환: (item_image, analysis)
    - 이미지가 아니거나 jpg/png가 아니면 ai.images.InvalidImage
    - AI 호출이 실패·지연되면 AnalysisUnavailable
    - AI가 물건을 못 찾으면 NoItemDetected
    실패한 경우 아무것도 저장하지 않습니다.
    """
    image = images.load_image(upload)

    try:
        analysis = analyze_item_image(images.to_jpeg_bytes(image, max_side=images.AI_MAX_SIDE))
    except AIError as exc:
        logger.info('사진 분석 실패 (user=%s): %s', user.pk, exc)
        raise AnalysisUnavailable from exc

    if not analysis.is_item:
        raise NoItemDetected

    public_image = images.blur(image) if analysis.sensitive else image

    name = f'items/{uuid.uuid4().hex}.jpg'
    original_key = private_storage.save(
        name, ContentFile(images.to_jpeg_bytes(image, max_side=ORIGINAL_MAX_SIDE))
    )
    public_name = public_storage.save(name, ContentFile(images.to_jpeg_bytes(public_image)))

    return ItemImage.objects.create(
        uploader=user,
        image_url=public_storage.url(public_name),
        original_image_key=original_key,
        is_blurred=analysis.sensitive,
        ai_tags=analysis.to_dict(),
    ), analysis


# ---------------------------------------------------------------------------
# 분실물·습득물 등록 공통: 설명문 생성 + 임베딩
# ---------------------------------------------------------------------------

def build_template_summary(info):
    """AI 설명문 생성이 실패했을 때 쓰는 고정 템플릿 설명문."""
    parts = []
    head = ' '.join(v for v in (info.get('color'), info.get('brand'), info.get('item_name')) if v)
    parts.append(f'{head}입니다.' if head else f"{info.get('category', '물건')}입니다.")
    if info.get('features'):
        parts.append('특징: ' + ', '.join(info['features']) + '.')
    if info.get('detail'):
        parts.append(info['detail'].strip())
    if info.get('chat_summary'):
        parts.append(info['chat_summary'].strip())
    return ' '.join(parts)


def build_summary_and_embedding(info):
    """
    물건 정보 → (설명문, 임베딩).

    설명문은 AI로 만들고 실패하면 템플릿으로 대체합니다.
    임베딩은 대체할 방법이 없어 실패하면 AnalysisUnavailable (→ 504).
    """
    try:
        summary = summarize_item(info)
    except AIError as exc:
        logger.info('설명문 생성 실패, 템플릿 사용: %s', exc)
        summary = build_template_summary(info)

    try:
        embedding = embed_text(summary)
    except AIError as exc:
        raise AnalysisUnavailable from exc
    return summary, embedding


def _item_info(data, chat_summary=None):
    """설명문 생성 입력. 습득물의 private_features는 공개 설명문에 들어가지 않도록 넣지 않음."""
    return {
        'category': data['category'],
        'item_name': data['item_name'],
        'color': data.get('color'),
        'brand': data.get('brand'),
        'features': data.get('features') or [],
        'detail': data.get('description'),
        'chat_summary': chat_summary,
    }


def _common_fields(data, summary, embedding):
    return {
        'image': data.get('image'),
        'place': data['place'],
        'location_detail': data.get('location_detail'),
        'category': data['category'],
        'item_name': data['item_name'],
        'color': data.get('color'),
        'brand': data.get('brand'),
        'features': data.get('features') or [],
        'description': summary,
        'text_embedding': embedding,
    }


def register_lost_item(user, data):
    """
    검증된 등록 데이터로 분실물 저장 → 특징 구체화 대화 연결 → 커밋 후 매칭 예약.

    data: LostItemCreateSerializer.validated_data (image, feature_chat, place 객체 포함)
    """
    feature_chat = data.get('feature_chat')
    summary, embedding = build_summary_and_embedding(
        _item_info(data, chat_summary=feature_chat.summary if feature_chat else None)
    )

    with transaction.atomic():
        lost_item = LostItem.objects.create(
            user=user,
            lost_from=data['lost_from'],
            lost_to=data['lost_to'],
            **_common_fields(data, summary, embedding),
        )
        if feature_chat:
            feature_chat.lost_item = lost_item
            feature_chat.save(update_fields=['lost_item', 'updated_at'])
        schedule_matching(LOST, lost_item.id)

    return lost_item


def register_found_item(user, data):
    """
    검증된 등록 데이터로 습득물 저장 → 커밋 후 매칭 예약.

    private_features는 저장만 하고 설명문·임베딩에는 쓰지 않음 (소유권 확인 질문 생성 전용).
    data: FoundItemCreateSerializer.validated_data (image, place 객체 포함)
    """
    summary, embedding = build_summary_and_embedding(_item_info(data))

    with transaction.atomic():
        found_item = FoundItem.objects.create(
            finder=user,
            found_at=data['found_at'],
            storage_status=data['storage_status'],
            storage_location=data.get('storage_location'),
            private_features=data.get('private_features'),
            **_common_fields(data, summary, embedding),
        )
        schedule_matching(FOUND, found_item.id)

    return found_item
