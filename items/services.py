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
