from drf_spectacular.utils import OpenApiExample, extend_schema_serializer
from rest_framework import serializers

from .models import Notification


class NotificationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Notification
        fields = [
            'id',
            'type',
            'title',
            'message',
            'target_id',
            'is_read',
            'created_at',
        ]


@extend_schema_serializer(
    examples=[
        OpenApiExample(
            '알림 목록 조회 성공 예시',
            value={
                'unread_count': 1,
                'notifications': [
                    {
                        'id': 102,
                        'type': 'MATCH_CANDIDATE',
                        'title': '새로운 매칭 후보가 발견되었어요!',
                        'message': "등록하신 '검정색 지갑'과 유사한 습득물이 등록되었습니다.",
                        'target_id': 12,
                        'is_read': False,
                        'created_at': '2026-11-13T09:40:00Z',
                    }
                ],
            },
            response_only=True,
        )
    ]
)
class NotificationListResponseSerializer(serializers.Serializer):
    unread_count = serializers.IntegerField()
    notifications = NotificationSerializer(many=True)


@extend_schema_serializer(
    examples=[
        OpenApiExample(
            '알림 읽음 처리 성공 예시',
            value={
                'id': 102,
                'is_read': True,
            },
            response_only=True,
        )
    ]
)
class NotificationReadResponseSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    is_read = serializers.BooleanField()