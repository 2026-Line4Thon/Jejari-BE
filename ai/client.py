"""
OpenAI 호출을 한곳에 모은 얇은 래퍼.

- 다른 앱은 openai SDK를 직접 쓰지 않고 이 모듈만 사용합니다.
- 실패(키 없음, 타임아웃, API 오류, JSON 파싱 실패)는 모두 AIError로 통일해서,
  호출하는 쪽이 "AI 없이 빈칸으로 진행" 같은 대체 흐름을 한 가지 방식으로 처리할 수 있게 합니다.
"""

import json
import logging

from django.conf import settings

logger = logging.getLogger(__name__)

_client = None


class AIError(Exception):
    """AI 호출 실패 (키 없음, 타임아웃, API 오류, 응답 형식 오류)."""


def get_client():
    global _client
    if not settings.OPENAI_API_KEY:
        raise AIError('OPENAI_API_KEY가 설정되지 않았습니다.')
    if _client is None:
        from openai import OpenAI

        _client = OpenAI(
            api_key=settings.OPENAI_API_KEY,
            timeout=settings.AI_TIMEOUT_SECONDS,
            max_retries=1,
        )
    return _client


def chat_json(*, model, messages, schema, schema_name, max_tokens=800):
    """JSON 스키마로 응답을 강제해서 dict로 반환."""
    import openai

    try:
        response = get_client().chat.completions.create(
            model=model,
            messages=messages,
            response_format={
                'type': 'json_schema',
                'json_schema': {'name': schema_name, 'schema': schema, 'strict': True},
            },
            max_completion_tokens=max_tokens,
        )
    except openai.OpenAIError as exc:
        logger.warning('OpenAI chat 호출 실패: %s', exc)
        raise AIError(str(exc)) from exc

    content = response.choices[0].message.content
    try:
        return json.loads(content)
    except (TypeError, json.JSONDecodeError) as exc:
        logger.warning('OpenAI 응답 JSON 파싱 실패: %r', content)
        raise AIError('AI 응답을 해석할 수 없습니다.') from exc


def embed(text):
    """설명문 → 텍스트 임베딩 벡터 (settings.EMBEDDING_DIMENSIONS 차원)."""
    import openai

    try:
        response = get_client().embeddings.create(
            model=settings.OPENAI_EMBEDDING_MODEL,
            input=text,
        )
    except openai.OpenAIError as exc:
        logger.warning('OpenAI embedding 호출 실패: %s', exc)
        raise AIError(str(exc)) from exc
    vector = response.data[0].embedding
    if len(vector) != settings.EMBEDDING_DIMENSIONS:
        raise AIError(f'임베딩 차원이 맞지 않습니다: {len(vector)}')
    return vector
