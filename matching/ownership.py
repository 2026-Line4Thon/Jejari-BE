"""
소유권 확인 (F-04, F-05, S-12, S-13).

정책
- 한 번 시도 = OwnershipCheck 1행, 질문 2개
- NEED_MORE면 같은 check에 추가 질문 1개 → 다시 애매하면 불일치
- 같은 후보에서 불일치 MAX_ATTEMPTS번이면 후보 LOCKED (이후 시도 429)
- MATCHED면 채팅방 생성 (chats.services.create_chat_room) → 분실물·습득물 CHATTING
- 질문의 기대 답변(expected)과 습득자의 private_features는 서버에만 두고 응답에 내려주지 않음

상태 흐름 (후보)
CANDIDATE ─시도→ VERIFYING ─일치→ MATCHED
                          └불일치→ MISMATCHED ─재시도→ VERIFYING … (불일치 2회) → LOCKED
"""

from django.db import transaction

from ai.services import AIError, generate_ownership_questions, judge_ownership
from chats.services import create_chat_room
from items.models import ItemStatus

from .models import MatchCandidate, OwnershipCheck
from .services import refresh_waiting_status

MAX_ATTEMPTS = 2
# 비공개 특징에 담긴 사실 수만큼 1~2개 (사실이 하나면 질문도 하나)
MAX_QUESTIONS = 2

OPEN_RESULTS = (OwnershipCheck.Result.PENDING, OwnershipCheck.Result.NEED_MORE)


class NotVerifiable(Exception):
    """제외·일치 판정·반환 완료 등으로 소유권 확인을 할 수 없는 후보 (→ 409)."""


class AttemptsExceeded(Exception):
    """시도 횟수 초과로 잠긴 후보 (→ 429)."""


class AlreadyJudged(Exception):
    """이미 판정이 끝난 확인 건 (→ 409)."""


class AnswersIncomplete(Exception):
    """질문 일부에 답하지 않음 (→ 400)."""


class JudgeUnavailable(Exception):
    """AI 질문 생성·판정 실패 (→ 504). 시도 횟수는 쓰지 않음."""


# ---------------------------------------------------------------------------
# 계산 값 (DB 컬럼 없음)
# ---------------------------------------------------------------------------

def mismatch_count(candidate):
    return candidate.ownership_checks.filter(result=OwnershipCheck.Result.MISMATCH).count()


def remaining_attempts(candidate):
    return max(0, MAX_ATTEMPTS - mismatch_count(candidate))


def attempt_no(check):
    return check.candidate.ownership_checks.filter(id__lte=check.id).count()


def public_questions(questions, only_unanswered_from=None):
    """[{question_id, text}] — expected는 빼고 내려줌."""
    items = questions if only_unanswered_from is None else questions[only_unanswered_from:]
    return [{'question_id': q['question_id'], 'text': q['text']} for q in items]


def _secret_and_public(found):
    """
    질문·판정에 쓰는 습득자 정보.
    secret: 습득자가 적은 비공개 특징. 비어 있을 때만 공개 features에 없는 AI 태그로 대신함
            (AI 태그는 주인도 기억하기 어려운 내용이 섞여 있어서, 비공개 특징이 있으면 쓰지 않음)
    public: 화면·매칭 근거에 드러나는 정보(설명문 포함) → 질문하면 안 되는 정보
    """
    if found.private_features and found.private_features.strip():
        secret = {'private_features': found.private_features.strip()}
    else:
        public_features = set(found.features or [])
        ai_features = (found.image.ai_tags or {}).get('features') or [] if found.image_id else []
        secret = {'hidden_ai_tags': [f for f in ai_features if f not in public_features]}
    public = {
        'category': found.category,
        'item_name': found.item_name,
        'color': found.color,
        'brand': found.brand,
        'features': found.features or [],
        'description': found.description,
    }
    return secret, public


def _set_items_status(candidate, status):
    for item in (candidate.lost_item, candidate.found_item):
        if item.status in (ItemStatus.WAITING, ItemStatus.CANDIDATE_FOUND, ItemStatus.VERIFYING):
            item.status = status
            item.save(update_fields=['status', 'updated_at'])


# ---------------------------------------------------------------------------
# 질문 생성 (POST /candidates/<id>/ownership-checks)
# ---------------------------------------------------------------------------

def start_check(candidate):
    """
    새 소유권 확인을 시작하고 (check, created)를 반환.
    답변을 기다리는 확인 건이 이미 있으면 새로 만들지 않고 그 건을 돌려줌 (시도 횟수 보호).
    """
    with transaction.atomic():
        candidate = (
            MatchCandidate.objects.select_for_update()
            .select_related('lost_item', 'found_item__image')
            .get(id=candidate.id)
        )
        if candidate.status == MatchCandidate.Status.LOCKED:
            raise AttemptsExceeded
        if (
            candidate.status in (MatchCandidate.Status.EXCLUDED, MatchCandidate.Status.MATCHED)
            or ItemStatus.COMPLETED in (candidate.lost_item.status, candidate.found_item.status)
        ):
            raise NotVerifiable

        open_check = candidate.ownership_checks.filter(result__in=OPEN_RESULTS).order_by('-id').first()
        if open_check:
            return open_check, False
        if remaining_attempts(candidate) == 0:
            raise AttemptsExceeded

    # AI 호출은 잠금 밖에서 (느린 호출 동안 행을 잡지 않도록)
    secret, public = _secret_and_public(candidate.found_item)
    try:
        generated = generate_ownership_questions(secret, public, max_count=MAX_QUESTIONS)
    except AIError as exc:
        raise JudgeUnavailable from exc

    with transaction.atomic():
        candidate = MatchCandidate.objects.select_for_update().get(id=candidate.id)
        open_check = candidate.ownership_checks.filter(result__in=OPEN_RESULTS).first()
        if open_check:  # 그 사이 다른 요청이 먼저 만든 경우
            return open_check, False
        check = OwnershipCheck.objects.create(
            candidate=candidate,
            questions=[
                {'question_id': i, 'text': q['text'], 'expected': q['expected']}
                for i, q in enumerate(generated, start=1)
            ],
        )
        candidate.status = MatchCandidate.Status.VERIFYING
        candidate.attempt_count = candidate.ownership_checks.count()
        candidate.save(update_fields=['status', 'attempt_count', 'updated_at'])
        _set_items_status(candidate, ItemStatus.VERIFYING)
    return check, True


# ---------------------------------------------------------------------------
# 답변 제출 (POST /ownership-checks/<id>/answers)
# ---------------------------------------------------------------------------

def _pending_questions(check):
    answered = {a['question_id'] for a in check.answers or []}
    return [q for q in check.questions if q['question_id'] not in answered]


def submit_answers(check, answers):
    """
    answers: [{question_id, answer}] → (result, extra)
    extra: MATCHED면 {'chat_room_id'}, NEED_MORE면 {'questions'}, MISMATCH면 {'remaining_attempts'}
    """
    if check.result not in OPEN_RESULTS:
        raise AlreadyJudged

    pending = _pending_questions(check)
    by_id = {a['question_id']: a['answer'].strip() for a in answers}
    if {q['question_id'] for q in pending} - {qid for qid, text in by_id.items() if text}:
        raise AnswersIncomplete

    new_answers = [{'question_id': q['question_id'], 'answer': by_id[q['question_id']]} for q in pending]
    all_answers = {a['question_id']: a['answer'] for a in (check.answers or []) + new_answers}
    qa = [
        {'question': q['text'], 'expected': q['expected'], 'answer': all_answers[q['question_id']]}
        for q in check.questions
    ]
    secret, public = _secret_and_public(check.candidate.found_item)
    allow_follow_up = check.result == OwnershipCheck.Result.PENDING  # 추가 질문은 한 번만

    try:
        result, follow_up = judge_ownership(qa, secret, public, allow_follow_up)
    except AIError as exc:
        raise JudgeUnavailable from exc  # 답변을 저장하지 않으므로 같은 답으로 다시 제출 가능

    with transaction.atomic():
        check = OwnershipCheck.objects.select_for_update().select_related('candidate').get(id=check.id)
        if check.result not in OPEN_RESULTS:
            raise AlreadyJudged
        candidate = MatchCandidate.objects.select_for_update().select_related(
            'lost_item__user', 'found_item__finder'
        ).get(id=check.candidate_id)

        check.answers = (check.answers or []) + new_answers

        if result == 'NEED_MORE':
            next_id = max(q['question_id'] for q in check.questions) + 1
            check.questions = check.questions + [{'question_id': next_id, **follow_up}]
            check.result = OwnershipCheck.Result.NEED_MORE
            check.save(update_fields=['answers', 'questions', 'result', 'updated_at'])
            return result, {'questions': public_questions(check.questions, len(check.questions) - 1)}

        if result == 'MATCHED':
            check.result = OwnershipCheck.Result.MATCHED
            check.save(update_fields=['answers', 'result', 'updated_at'])
            candidate.status = MatchCandidate.Status.MATCHED
            candidate.save(update_fields=['status', 'updated_at'])
            chat_room, _ = create_chat_room(candidate)  # 분실물·습득물 CHATTING + 양측 알림
            return result, {'chat_room_id': chat_room.id}

        check.result = OwnershipCheck.Result.MISMATCH
        check.save(update_fields=['answers', 'result', 'updated_at'])
        remaining = remaining_attempts(candidate)
        candidate.status = (
            MatchCandidate.Status.LOCKED if remaining == 0 else MatchCandidate.Status.MISMATCHED
        )
        candidate.save(update_fields=['status', 'updated_at'])
        _set_items_status(candidate, ItemStatus.CANDIDATE_FOUND)
        refresh_waiting_status(candidate.lost_item)
        refresh_waiting_status(candidate.found_item)
        return result, {'remaining_attempts': remaining}
