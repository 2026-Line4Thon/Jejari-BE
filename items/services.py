import logging
import uuid

from django.core.files.base import ContentFile

from ai import images
from ai.services import AIError, analyze_item_image
from common.storage import private_storage, public_storage

from .models import ItemImage

logger = logging.getLogger(__name__)

ORIGINAL_MAX_SIDE = 3000


class NoItemDetected(Exception):
    """AI가 사진에서 분실물로 볼 물건을 찾지 못함 (→ 422)."""


def create_analyzed_image(user, upload):
    """
    사진 업로드 → AI 분석 → 블러 → 공개/비공개 저장 → ItemImage 생성.

    반환: (item_image, analysis)  analysis는 AI 실패 시 None
    - AI가 물건을 못 찾으면 NoItemDetected (아무것도 저장하지 않음)
    - AI 호출이 실패·지연되면 분석 없이 진행 (사용자가 직접 입력).
      이때 민감정보 여부를 알 수 없으므로 공개용 이미지는 블러 처리
    """
    image = images.load_image(upload)

    try:
        analysis = analyze_item_image(images.to_jpeg_bytes(image, max_side=images.AI_MAX_SIDE))
    except AIError:
        logger.info('사진 분석 실패, 분석 없이 진행 (user=%s)', user.pk)
        analysis = None

    if analysis is not None and not analysis.is_item:
        raise NoItemDetected

    should_blur = analysis.sensitive if analysis is not None else True
    public_image = images.blur(image) if should_blur else image

    name = f'items/{uuid.uuid4().hex}.jpg'
    original_key = private_storage.save(
        name, ContentFile(images.to_jpeg_bytes(image, max_side=ORIGINAL_MAX_SIDE))
    )
    public_name = public_storage.save(name, ContentFile(images.to_jpeg_bytes(public_image)))

    return ItemImage.objects.create(
        uploader=user,
        image_url=public_storage.url(public_name),
        original_image_key=original_key,
        is_blurred=should_blur,
        ai_tags=analysis.to_dict() if analysis is not None else None,
    ), analysis
