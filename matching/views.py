from django.conf import settings
from drf_spectacular.utils import extend_schema, inline_serializer
from rest_framework import serializers, status
from rest_framework.exceptions import NotFound
from rest_framework.permissions import IsAdminUser
from rest_framework.response import Response
from rest_framework.views import APIView

from items.models import LostItem

from .engine import LOST, run_matching
from .models import MatchCandidate


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
