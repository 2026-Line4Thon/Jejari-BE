"""
AI 특징 구체화 대화 (C-04, S-03).

- 질문 순서는 STEPS로 코드에 고정. 사진·설명에서 이미 파악한 항목은 건너뜀
- AI는 (1) 파악된 항목 추출 (2) 질문 문장·선택지 생성만 맡고, 실패하면 템플릿으로 대체
- 항목마다 FeatureChatTurn 1행. 이미 파악한 항목도 KNOWN_QUESTION 표시로 남겨서
  대화가 끝났을 때 항목별 최종 값을 턴만으로 계산할 수 있게 함
- 종료 시 요약(summary)을 만들어 FeatureChat에 저장 → 분실물 등록(feature_chat_id) 때 설명문에 반영
"""

import logging

from django.db import transaction

from ai.services import AIError, extract_known_features, summarize_item, write_feature_question

from .models import FeatureChat, FeatureChatTurn

logger = logging.getLogger(__name__)

STEPS = [choice.value for choice in FeatureChatTurn.StepCategory]

TEMPLATE_QUESTIONS = {
    'category': ('어떤 종류의 물건인가요?', ['지갑', '이어폰', '휴대폰']),
    'color': ('{noun} 색상은 무엇이었나요?', ['검정', '흰색', '남색']),
    'size': ('{noun} 크기는 어느 정도였나요?', ['손바닥보다 작아요', '손바닥만 해요', '손바닥보다 커요']),
    'material': ('{noun} 재질은 무엇이었나요?', ['가죽', '천', '플라스틱']),
    'shape': ('{noun} 모양은 어땠나요?', ['네모난 모양', '둥근 모양', '길쭉한 모양']),
    'marks': ('{noun}에 흠집이나 스티커 같은 표시가 있었나요?',
              ['흠집이 있어요', '스티커가 붙어 있어요', '특별한 표시는 없어요']),
    'brand': ('{noun} 브랜드를 기억하나요?', ['로고가 있었어요', '브랜드 없는 제품이에요', '직접 입력할게요']),
}


class ChatFinished(Exception):
    """이미 종료된 대화 (→ 409)."""


class WrongStep(Exception):
    """현재 질문과 다른 항목에 답변 (→ 400)."""

    def __init__(self, current_step):
        super().__init__(current_step)
        self.current_step = current_step


# ---------------------------------------------------------------------------
# 항목별 값 계산
# ---------------------------------------------------------------------------

def features_of(chat):
    """항목별 최종 값. 모르거나 건너뛴 항목은 None."""
    values = dict.fromkeys(STEPS)
    for turn in chat.turns.all():
        if turn.answer and not turn.is_skipped:
            values[turn.step_category] = turn.answer
    return values


def known_of(chat):
    return {k: v for k, v in features_of(chat).items() if v}


def _current_turn(chat):
    return chat.turns.filter(answer__isnull=True, is_skipped=False).order_by('created_at', 'id').last()


def _remaining_steps(chat):
    done = set(chat.turns.values_list('step_category', flat=True))
    return [step for step in STEPS if step not in done]


# ---------------------------------------------------------------------------
# 질문
# ---------------------------------------------------------------------------

def _question_for(step, known):
    try:
        return write_feature_question(step, known)
    except AIError as exc:
        logger.info('특징 질문 생성 실패, 템플릿 사용 (%s): %s', step, exc)
        text, options = TEMPLATE_QUESTIONS[step]
        return {'text': text.format(noun=known.get('category') or '물건'), 'options': list(options)}


def _ask_next(chat):
    """다음 질문 턴을 만들고 {step, text, options}를 반환. 물어볼 항목이 없으면 None."""
    remaining = _remaining_steps(chat)
    if not remaining:
        return None
    step = remaining[0]
    question = _question_for(step, known_of(chat))
    FeatureChatTurn.objects.create(chat=chat, step_category=step, question=question['text'])
    return {'step': step, **question}


# ---------------------------------------------------------------------------
# 요약 (종료)
# ---------------------------------------------------------------------------

def _summary_for(chat, features):
    from .services import build_template_summary

    info = {
        'category': features['category'],
        'item_name': None,
        'color': features['color'],
        'brand': features['brand'],
        'features': [features[k] for k in ('size', 'material', 'shape', 'marks') if features[k]],
        'detail': chat.input_description,
    }
    try:
        return summarize_item(info)
    except AIError as exc:
        logger.info('특징 요약 생성 실패, 템플릿 사용: %s', exc)
        return build_template_summary({**info, 'item_name': features['category']})


def finish(chat):
    """대화를 끝내고 (summary, features)를 반환. 답하지 않은 질문은 그대로 비워 둠."""
    with transaction.atomic():
        chat = FeatureChat.objects.select_for_update().get(id=chat.id)
        if chat.is_finished:
            raise ChatFinished
        features = features_of(chat)
        chat.summary = _summary_for(chat, features)
        chat.is_finished = True
        chat.save(update_fields=['summary', 'is_finished', 'updated_at'])
    return chat.summary, features


# ---------------------------------------------------------------------------
# 시작 · 답변
# ---------------------------------------------------------------------------

def start(user, image, description):
    """
    대화 시작 → (chat, known, question).
    question이 None이면 모든 항목을 이미 알고 있어 바로 종료된 것 (chat.is_finished=True).
    """
    tags = image.ai_tags if image else None
    try:
        known = extract_known_features(tags, description)
    except AIError as exc:
        logger.info('특징 추출 실패, 사진 태그만 사용: %s', exc)
        known = {step: (tags or {}).get(step) for step in STEPS}

    with transaction.atomic():
        chat = FeatureChat.objects.create(user=user, input_description=description)
        FeatureChatTurn.objects.bulk_create([
            FeatureChatTurn(
                chat=chat, step_category=step, question=FeatureChatTurn.KNOWN_QUESTION, answer=value
            )
            for step in STEPS if (value := known.get(step))
        ])
        question = _ask_next(chat)

    if question is None:
        finish(chat)
        chat.refresh_from_db()
    return chat, known_of(chat), question


def answer(chat, step, text, is_skipped):
    """
    현재 질문에 답변 → (question, finished)
    다음 질문이 있으면 (question, None), 끝났으면 (None, (summary, features)).
    """
    with transaction.atomic():
        chat = FeatureChat.objects.select_for_update().get(id=chat.id)
        if chat.is_finished:
            raise ChatFinished
        turn = _current_turn(chat)
        if turn is None or turn.step_category != step:
            raise WrongStep(turn.step_category if turn else None)

        turn.is_skipped = is_skipped
        turn.answer = None if is_skipped else text
        turn.save(update_fields=['answer', 'is_skipped', 'updated_at'])
        question = _ask_next(chat)

    if question is not None:
        return question, None
    return None, finish(chat)
