from django.conf import settings
from drf_spectacular.utils import OpenApiResponse, extend_schema, inline_serializer
from rest_framework import serializers, status
from rest_framework.exceptions import NotFound, PermissionDenied
from rest_framework.permissions import IsAdminUser, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from chats.models import ChatRoom
from items.models import LostItem

from . import ownership
from .engine import LOST, run_matching
from .models import MatchCandidate, OwnershipCheck
from .serializers import (
    CandidateDetailSerializer,
    CandidateListItemSerializer,
    CandidateListResponseSerializer,
    CandidateRejectResponseSerializer,
    OwnershipAnswerResponseSerializer,
    OwnershipAnswersSerializer,
    OwnershipCheckCreateResponseSerializer,
    OwnershipCheckDetailSerializer,
)
from .services import CandidateLocked, reject_candidate


class DevMatchingRunView(APIView):
    """
    (개발용) 매칭 수동 실행. 관리자만 호출 가능, DEBUG=False면 404.
    지정한 분실물을 즉시 매칭하고 내부 점수를 포함해 반환한다.
    이미 후보로 묶인 쌍은 다시 만들지 않으므로 새로 생긴 후보만 반환된다.
    """

    permission_classes = [IsAdminUser]

    @extend_schema(
        request=None,
        responses={200: inline_serializer('DevMatchingRunResponse', {
            'lost_item_id': serializers.IntegerField(),
            'candidates_created': serializers.IntegerField(),
            'candidates': serializers.ListField(child=serializers.DictField()),
        })},
    )
    def post(self, request, lost_item_id):
        if not settings.DEBUG or not LostItem.objects.filter(id=lost_item_id).exists():
            raise NotFound('분실물을 찾을 수 없습니다.')

        created = run_matching(LOST, lost_item_id)
        labels = dict(MatchCandidate.SimilarityLabel.choices)
        return Response({
            'lost_item_id': lost_item_id,
            'candidates_created': len(created),
            'candidates': [
                {
                    'candidate_id': r.candidate.id,
                    'found_item_id': r.found.id,
                    'total_score': r.total,
                    'scores': r.scores,
                    'similarity_label': labels[r.label],
                }
                for r in created
            ],
        }, status=status.HTTP_200_OK)


# ---------------------------------------------------------------------------
# 매칭 후보 (F-02, F-03) — 분실물 등록자 본인만
# ---------------------------------------------------------------------------

def _get_own_candidate(request, candidate_id):
    candidate = (
        MatchCandidate.objects
        .select_related('lost_item', 'found_item__image', 'found_item__place')
        .filter(id=candidate_id)
        .first()
    )
    if candidate is None:
        raise NotFound('매칭 후보를 찾을 수 없습니다.')
    if candidate.lost_item.user_id != request.user.id:
        raise PermissionDenied()
    return candidate


class LostItemCandidateListView(APIView):
    """분실물의 매칭 후보를 유사도 높은 순으로. 제외한 후보와 숫자 점수는 내려주지 않음."""

    permission_classes = [IsAuthenticated]

    @extend_schema(responses={200: CandidateListResponseSerializer})
    def get(self, request, item_id):
        lost_item = LostItem.objects.filter(id=item_id).first()
        if lost_item is None:
            raise NotFound('분실물을 찾을 수 없습니다.')
        if lost_item.user_id != request.user.id:
            raise PermissionDenied()

        candidates = (
            lost_item.candidates
            .exclude(status=MatchCandidate.Status.EXCLUDED)
            .select_related('found_item__image', 'found_item__place')
            .order_by('-total_score', 'id')
        )
        data = {
            'lost_item_id': lost_item.id,
            'status': lost_item.status,
            'candidates': CandidateListItemSerializer(
                candidates, many=True, context={'request': request}
            ).data,
        }
        if not data['candidates']:
            data['message'] = '비슷한 물건이 등록되면 알려드릴게요.'
        return Response(data, status=status.HTTP_200_OK)


class CandidateDetailView(APIView):
    """후보 습득물의 공개 정보와 항목별 매칭 근거. 비공개 특징은 내려주지 않음."""

    permission_classes = [IsAuthenticated]

    @extend_schema(responses={200: CandidateDetailSerializer})
    def get(self, request, candidate_id):
        candidate = _get_own_candidate(request, candidate_id)
        serializer = CandidateDetailSerializer(candidate, context={'request': request})
        return Response(serializer.data, status=status.HTTP_200_OK)


class CandidateRejectView(APIView):
    """「다른 물건이에요」로 후보 제외. 소유권 확인이 진행된 후보는 409."""

    permission_classes = [IsAuthenticated]

    @extend_schema(request=None, responses={200: CandidateRejectResponseSerializer})
    def post(self, request, candidate_id):
        candidate = _get_own_candidate(request, candidate_id)
        try:
            candidate = reject_candidate(candidate)
        except CandidateLocked:
            return Response(
                {'detail': '이미 소유권 확인이 진행된 후보는 제외할 수 없습니다.'},
                status=status.HTTP_409_CONFLICT,
            )
        return Response({
            'candidate_id': candidate.id,
            'status': candidate.status,
            'message': '후보에서 제외했어요.',
        }, status=status.HTTP_200_OK)


# ---------------------------------------------------------------------------
# 소유권 확인 (F-04, F-05, S-12, S-13) — 분실물 등록자 본인만
# ---------------------------------------------------------------------------

RESULT_MESSAGES = {
    'MATCHED': '소유권이 확인되었어요. 습득자와 채팅을 시작할 수 있어요.',
    'NEED_MORE': '조금 더 확인이 필요해요.',
    'MISMATCH': '답변이 일치하지 않아요.',
}


def _judge_timeout():
    return Response(
        {'detail': '확인 시간이 초과되었습니다. 잠시 후 다시 시도해 주세요.'},
        status=status.HTTP_504_GATEWAY_TIMEOUT,
    )


def _get_own_check(request, check_id):
    check = (
        OwnershipCheck.objects
        .select_related('candidate__lost_item', 'candidate__found_item__image')
        .filter(id=check_id)
        .first()
    )
    if check is None:
        raise NotFound('소유권 확인 내역을 찾을 수 없습니다.')
    if check.candidate.lost_item.user_id != request.user.id:
        raise PermissionDenied()
    return check


class OwnershipCheckCreateView(APIView):
    """「내 물건이 맞아요」: 습득자의 비공개 특징으로 정답이 드러나지 않는 질문 2개 생성."""

    permission_classes = [IsAuthenticated]

    @extend_schema(
        request=None,
        responses={
            201: OwnershipCheckCreateResponseSerializer,
            200: OpenApiResponse(OwnershipCheckCreateResponseSerializer, description='답변 대기 중인 확인 건 재사용'),
            409: OpenApiResponse(description='제외·일치 판정·반환 완료된 후보'),
            429: OpenApiResponse(description='시도 횟수 초과'),
            504: OpenApiResponse(description='질문 생성 실패'),
        },
    )
    def post(self, request, candidate_id):
        candidate = _get_own_candidate(request, candidate_id)
        try:
            check, created = ownership.start_check(candidate)
        except ownership.NotVerifiable:
            return Response(
                {'detail': '소유권 확인을 진행할 수 없는 후보입니다.'}, status=status.HTTP_409_CONFLICT
            )
        except ownership.AttemptsExceeded:
            return Response(
                {'detail': '소유권 확인 시도 횟수를 초과했습니다.'},
                status=status.HTTP_429_TOO_MANY_REQUESTS,
            )
        except ownership.JudgeUnavailable:
            return _judge_timeout()

        unanswered = [q for q in check.questions
                      if q['question_id'] not in {a['question_id'] for a in check.answers or []}]
        data = {
            'check_id': check.id,
            'candidate_id': candidate.id,
            'attempt_no': ownership.attempt_no(check),
            'remaining_attempts': ownership.remaining_attempts(check.candidate),
            'questions': ownership.public_questions(unanswered),
        }
        return Response(
            OwnershipCheckCreateResponseSerializer(data).data,
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )


class OwnershipAnswerView(APIView):
    """답변 제출 → AI가 의미 일치 판정 (MATCHED / NEED_MORE / MISMATCH)."""

    permission_classes = [IsAuthenticated]

    @extend_schema(
        request=OwnershipAnswersSerializer,
        responses={
            200: OwnershipAnswerResponseSerializer,
            400: OpenApiResponse(description='답변 누락, 모든 질문에 답하지 않음'),
            409: OpenApiResponse(description='이미 판정이 끝난 확인 건'),
            504: OpenApiResponse(description='판정 실패 (답변은 저장되지 않음, 다시 제출 가능)'),
        },
    )
    def post(self, request, check_id):
        check = _get_own_check(request, check_id)
        serializer = OwnershipAnswersSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            result, extra = ownership.submit_answers(check, serializer.validated_data['answers'])
        except ownership.AlreadyJudged:
            return Response(
                {'detail': '이미 판정이 완료된 소유권 확인입니다.'}, status=status.HTTP_409_CONFLICT
            )
        except ownership.AnswersIncomplete:
            return Response({'detail': '모든 질문에 답변해 주세요.'}, status=status.HTTP_400_BAD_REQUEST)
        except ownership.JudgeUnavailable:
            return _judge_timeout()

        data = {'check_id': check.id, 'result': result, 'message': RESULT_MESSAGES[result], **extra}
        return Response(OwnershipAnswerResponseSerializer(data).data, status=status.HTTP_200_OK)


class OwnershipCheckDetailView(APIView):
    """판정 결과 조회. 질문의 정답과 비공개 특징은 내려주지 않음."""

    permission_classes = [IsAuthenticated]

    @extend_schema(responses={200: OwnershipCheckDetailSerializer})
    def get(self, request, check_id):
        check = _get_own_check(request, check_id)
        chat_room = None
        if check.result == OwnershipCheck.Result.MATCHED:
            chat_room = ChatRoom.objects.filter(candidate_id=check.candidate_id).first()
        data = {
            'check_id': check.id,
            'candidate_id': check.candidate_id,
            'attempt_no': ownership.attempt_no(check),
            'result': check.result,
            'chat_room_id': chat_room.id if chat_room else None,
            'remaining_attempts': ownership.remaining_attempts(check.candidate),
            'created_at': check.created_at,
        }
        return Response(OwnershipCheckDetailSerializer(data).data, status=status.HTTP_200_OK)
