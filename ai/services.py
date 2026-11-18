import base64
import json
import re
from dataclasses import asdict, dataclass, field

from django.conf import settings

from . import client, prompts
from .client import AIError

__all__ = ['AIError', 'ImageAnalysis', 'analyze_item_image', 'summarize_item', 'embed_text']

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


# 프롬프트로 금지해도 모델이 사진 속 개인정보를 옮겨 적는 경우가 있어서 코드에서 한 번 더 거른다.
# (숫자 3자리 이상 또는 개인정보 항목명이 들어간 특징은 버림)
_PERSONAL_INFO_PATTERN = re.compile(
    r'\d{3,}|이름|성명|학번|학생\s*번호|학과|전공|생년|연락처|전화|휴대폰\s*번호|카드\s*번호|계좌|주소|이메일|@'
)


def _is_safe_feature(text):
    return not _PERSONAL_INFO_PATTERN.search(text)


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

    features = [
        f for f in (_clean_text(x) for x in raw.get('features') or []) if f and _is_safe_feature(f)
    ]
    return ImageAnalysis(
        is_item=raw['is_item'],
        category=_clean_text(raw.get('category')),
        item_name=_clean_text(raw.get('item_name')),
        color=_clean_text(raw.get('color')),
        brand=_clean_text(raw.get('brand')),
        features=features[:MAX_FEATURES],
        sensitive=bool(raw.get('sensitive')),
    )


def summarize_item(info):
    """
    물건 정보(dict) → 설명문 한 문단. 분실물·습득물이 같은 형식으로 써서 임베딩 비교가 공정하게 되도록 함.

    info 키: category, item_name, color, brand, features(list), detail(사용자 상세 설명), chat_summary
    """
    payload = {k: v for k, v in info.items() if v not in (None, '', [])}
    raw = client.chat_json(
        model=settings.OPENAI_TEXT_MODEL,
        schema=prompts.ITEM_SUMMARY_SCHEMA,
        schema_name='item_summary',
        max_tokens=300,
        messages=[
            {'role': 'system', 'content': prompts.ITEM_SUMMARY_SYSTEM},
            {'role': 'user', 'content': json.dumps(payload, ensure_ascii=False)},
        ],
    )
    summary = _clean_text(raw.get('summary')) if isinstance(raw, dict) else None
    if not summary:
        raise AIError('설명문이 비어 있습니다.')
    return summary


def embed_text(text):
    """설명문 → 임베딩 벡터."""
    return client.embed(text)
