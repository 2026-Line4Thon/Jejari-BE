import base64
from dataclasses import asdict, dataclass, field

from django.conf import settings

from . import client, prompts
from .client import AIError

__all__ = ['AIError', 'ImageAnalysis', 'analyze_item_image']

MAX_FEATURES = 5


@dataclass
class ImageAnalysis:
    is_item: bool
    category: str | None = None
    item_name: str | None = None
    color: str | None = None
    brand: str | None = None
    features: list[str] = field(default_factory=list)
    sensitive: bool = False

    def to_dict(self):
        return asdict(self)


def _clean_text(value):
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value or None


def analyze_item_image(jpeg_bytes):
    """
    사진(JPEG bytes) → ImageAnalysis.

    실패 시 AIError를 던집니다. 물건을 찾지 못한 경우는 실패가 아니라 is_item=False로 반환합니다.
    """
    data_url = 'data:image/jpeg;base64,' + base64.b64encode(jpeg_bytes).decode('ascii')
    raw = client.chat_json(
        model=settings.OPENAI_VISION_MODEL,
        schema=prompts.IMAGE_ANALYSIS_SCHEMA,
        schema_name='item_image_analysis',
        messages=[
            {'role': 'system', 'content': prompts.IMAGE_ANALYSIS_SYSTEM},
            {
                'role': 'user',
                'content': [
                    {'type': 'text', 'text': prompts.IMAGE_ANALYSIS_USER},
                    {'type': 'image_url', 'image_url': {'url': data_url, 'detail': 'low'}},
                ],
            },
        ],
    )

    if not isinstance(raw, dict) or not isinstance(raw.get('is_item'), bool):
        raise AIError('AI 응답 형식이 올바르지 않습니다.')

    features = [f for f in (_clean_text(x) for x in raw.get('features') or []) if f]
    return ImageAnalysis(
        is_item=raw['is_item'],
        category=_clean_text(raw.get('category')),
        item_name=_clean_text(raw.get('item_name')),
        color=_clean_text(raw.get('color')),
        brand=_clean_text(raw.get('brand')),
        features=features[:MAX_FEATURES],
        sensitive=bool(raw.get('sensitive')),
    )
