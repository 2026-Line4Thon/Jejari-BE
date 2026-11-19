from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Notification
from .serializers import (
    NotificationSerializer,
    NotificationListResponseSerializer,
    NotificationReadResponseSerializer,
)


# 알림 목록 조회 (GET /notifications)
class NotificationListView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=['Notifications'],
        summary='알림 목록 조회',
        description='새 매칭 후보, 소유권 확인 결과, 채팅 시작 알림을 최신 시간순으로 조회합니다.',
        responses={200: NotificationListResponseSerializer},
    )
    def get(self, request):
        notifications = Notification.objects.filter(user=request.user)
        unread_count = notifications.filter(is_read=False).count()
        serializer = NotificationSerializer(notifications, many=True)

        return Response(
            {
                "unread_count": unread_count,
                "notifications": serializer.data,
            },
            status=status.HTTP_200_OK
        )


# 알림 읽음 처리 (PATCH /notifications/<int:notification_id>/read)
class NotificationReadView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=['Notifications'],
        summary='알림 읽음 처리',
        description='사용자가 특정 알림을 눌렀을 때 해당 알림을 읽음(is_read: true) 상태로 업데이트합니다.',
        request=None,
        responses={200: NotificationReadResponseSerializer},
    )
    def patch(self, request, notification_id):
        try:
            notification = Notification.objects.get(id=notification_id)
        except Notification.DoesNotExist:
            return Response(
                {"detail": "해당 알림을 찾을 수 없습니다."},
                status=status.HTTP_404_NOT_FOUND
            )

        if notification.user != request.user:
            return Response(
                {"detail": "해당 알림에 대한 접근 권한이 없습니다."},
                status=status.HTTP_403_FORBIDDEN
            )

        if not notification.is_read:
            notification.is_read = True
            notification.save(update_fields=['is_read', 'updated_at'])

        return Response(
            {
                "id": notification.id,
                "is_read": notification.is_read,
            },
            status=status.HTTP_200_OK
        )