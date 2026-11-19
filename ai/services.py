import base64
import json
import re
from dataclasses import asdict, dataclass, field

from django.conf import settings

from . import client, prompts
from .client import AIError

__all__ = [
    'AIError', 'ImageAnalysis', 'analyze_item_image', 'summarize_item', 'embed_text', 'write_match_reasons',
    'generate_ownership_questions', 'judge_ownership', 'extract_known_features', 'write_feature_question',
]

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


def write_match_reasons(payload):
    """두 물건의 공개 정보 + 규칙 기반 판정 → 항목별 근거 문장 목록 [{field, text}]."""
    raw = client.chat_json(
        model=settings.OPENAI_TEXT_MODEL,
        schema=prompts.MATCH_REASONS_SCHEMA,
        schema_name='match_reasons',
        max_tokens=600,
        messages=[
            {'role': 'system', 'content': prompts.MATCH_REASONS_SYSTEM},
            {'role': 'user', 'content': json.dumps(payload, ensure_ascii=False)},
        ],
    )
    reasons = raw.get('reasons') if isinstance(raw, dict) else None
    if not isinstance(reasons, list):
        raise AIError('매칭 근거 응답 형식이 올바르지 않습니다.')
    return reasons


def _question_pairs(items):
    pairs = []
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict):
            continue
        text, expected = _clean_text(item.get('text')), _clean_text(item.get('expected'))
        if text and expected:
            pairs.append({'text': text, 'expected': expected})
    return pairs


def generate_ownership_questions(secret, public, count=2):
    """
    습득자의 비공개 정보(secret) → 정답이 드러나지 않는 질문 [{text, expected}] count개.
    expected(기대 답변)는 서버에만 저장하고 응답에 내려주지 않습니다.
    """
    raw = client.chat_json(
        model=settings.OPENAI_TEXT_MODEL,
        schema=prompts.OWNERSHIP_QUESTIONS_SCHEMA,
        schema_name='ownership_questions',
        max_tokens=500,
        messages=[
            {'role': 'system', 'content': prompts.OWNERSHIP_QUESTIONS_SYSTEM.format(count=count)},
            {'role': 'user', 'content': json.dumps({'secret': secret, 'public': public}, ensure_ascii=False)},
        ],
    )
    questions = _question_pairs(raw.get('questions') if isinstance(raw, dict) else None)
    if len(questions) < count:
        raise AIError('소유권 확인 질문을 만들지 못했습니다.')
    return questions[:count]


def judge_ownership(qa, secret, public, allow_follow_up):
    """
    qa: [{question, expected, answer}] → (result, follow_up)
    result는 MATCHED / NEED_MORE / MISMATCH, follow_up은 NEED_MORE일 때 {text, expected}.
    """
    raw = client.chat_json(
        model=settings.OPENAI_TEXT_MODEL,
        schema=prompts.OWNERSHIP_JUDGE_SCHEMA,
        schema_name='ownership_judge',
        max_tokens=400,
        messages=[
            {'role': 'system', 'content': prompts.OWNERSHIP_JUDGE_SYSTEM},
            {'role': 'user', 'content': json.dumps(
                {'secret': secret, 'public': public, 'qa': qa, 'allow_follow_up': allow_follow_up},
                ensure_ascii=False,
            )},
        ],
    )
    result = raw.get('result') if isinstance(raw, dict) else None
    if result not in ('MATCHED', 'NEED_MORE', 'MISMATCH'):
        raise AIError('판정 결과 형식이 올바르지 않습니다.')

    follow_up = None
    if result == 'NEED_MORE':
        pairs = _question_pairs([raw.get('follow_up')])
        if not allow_follow_up or not pairs:
            result = 'MISMATCH'  # 더 물어볼 수 없으면 애매한 답은 불일치로 처리
        else:
            follow_up = pairs[0]
    return result, follow_up


def extract_known_features(tags, description):
    """사진 분석 태그·사용자 설명 → 특징 항목별 값 dict (모르면 None)."""
    raw = client.chat_json(
        model=settings.OPENAI_TEXT_MODEL,
        schema=prompts.FEATURE_EXTRACT_SCHEMA,
        schema_name='feature_extract',
        max_tokens=300,
        messages=[
            {'role': 'system', 'content': prompts.FEATURE_EXTRACT_SYSTEM},
            {'role': 'user', 'content': json.dumps(
                {'tags': tags or {}, 'description': description}, ensure_ascii=False
            )},
        ],
    )
    if not isinstance(raw, dict):
        raise AIError('특징 추출 응답 형식이 올바르지 않습니다.')
    return {step: _clean_text(raw.get(step)) for step in prompts.FEATURE_STEPS}


_NOT_SURE_OPTION = re.compile(r'모르|모름|기억\s*(이\s*)?안|없어요|없습니다|아니요')


def write_feature_question(step, known):
    """항목(step) 하나에 대한 질문 문장과 선택지 3개."""
    raw = client.chat_json(
        model=settings.OPENAI_TEXT_MODEL,
        schema=prompts.FEATURE_QUESTION_SCHEMA,
        schema_name='feature_question',
        max_tokens=200,
        messages=[
            {'role': 'system', 'content': prompts.FEATURE_QUESTION_SYSTEM},
            {'role': 'user', 'content': json.dumps({'step': step, 'known': known}, ensure_ascii=False)},
        ],
    )
    text = _clean_text(raw.get('text')) if isinstance(raw, dict) else None
    options = [
        o for o in (_clean_text(x) for x in (raw.get('options') or []))
        if o and not _NOT_SURE_OPTION.search(o)  # 화면에서 따로 제공하는 「잘 모르겠어요」류는 제외
    ] if text else []
    if not text or len(options) < 2:
        raise AIError('특징 질문을 만들지 못했습니다.')
    return {'text': text, 'options': options[:3]}
