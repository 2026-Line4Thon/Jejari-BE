from django.conf import settings
from drf_spectacular.utils import extend_schema, inline_serializer
from rest_framework import serializers, status
from rest_framework.exceptions import NotFound, PermissionDenied
from rest_framework.permissions import IsAdminUser, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from items.models import LostItem

from .engine import LOST, run_matching
from .models import MatchCandidate
from .serializers import (
    CandidateDetailSerializer,
    CandidateListItemSerializer,
    CandidateListResponseSerializer,
    CandidateRejectResponseSerializer,
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
