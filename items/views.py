from django.shortcuts import render

# Create your views here.

from django.core.paginator import Paginator, EmptyPage
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework import status

from .models import FoundItem, MatchCandidate, Notification
from .serializers import (
    FoundItemListSerializer,
    FoundItemDetailSerializer,
    NotificationSerializer,
)


# 1. 메인 홈 정보 조회 (GET /home)
class HomeView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        my_matching_count = MatchCandidate.objects.filter(
            lost_item__owner=request.user,
            status__in=['PENDING', 'VERIFIED']
        ).count()

        recent_items = FoundItem.objects.exclude(status='COMPLETED')[:10]
        serializer = FoundItemListSerializer(recent_items, many=True)

        return Response(
            {
                "my_matching_count": my_matching_count,
                "recent_found_items": serializer.data,
            },
            status=status.HTTP_200_OK
        )


# 2. 습득물 전체 목록 조회 (GET /items/found?page=1&size=10)
class FoundItemListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        page_param = request.query_params.get('page', '1')
        size_param = request.query_params.get('size', '10')

        # page 정수 검증
        try:
            page = int(page_param)
            if page < 1:
                raise ValueError
        except ValueError:
            return Response(
                {"page": ["유효한 정수(integer)를 입력하세요."]},
                status=status.HTTP_400_BAD_REQUEST
            )

        # size 정수 검증
        try:
            size = int(size_param)
            if size < 1:
                raise ValueError
        except ValueError:
            return Response(
                {"size": ["유효한 정수(integer)를 입력하세요."]},
                status=status.HTTP_400_BAD_REQUEST
            )

        queryset = FoundItem.objects.exclude(status='COMPLETED').order_by('-created_at')
        paginator = Paginator(queryset, size)
        total_count = paginator.count

        try:
            page_obj = paginator.page(page)
            items = page_obj.object_list
            has_next = page_obj.has_next()
        except EmptyPage:
            items = []
            has_next = False

        serializer = FoundItemListSerializer(items, many=True)

        return Response(
            {
                "total_count": total_count,
                "has_next": has_next,
                "items": serializer.data,
            },
            status=status.HTTP_200_OK
        )


# 3. 습득물 상세 조회 (GET /items/found/<int:item_id>)
class FoundItemDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, item_id):
        try:
            found_item = FoundItem.objects.get(id=item_id)
        except FoundItem.DoesNotExist:
            return Response(
                {"detail": "해당 습득물 정보를 찾을 수 없습니다."},
                status=status.HTTP_404_NOT_FOUND
            )

        serializer = FoundItemDetailSerializer(found_item)
        return Response(serializer.data, status=status.HTTP_200_OK)


# 4. 알림 목록 조회 (GET /notifications)
class NotificationListView(APIView):
    permission_classes = [IsAuthenticated]

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


# 5. 알림 읽음 처리 (PATCH /notifications/<int:notification_id>/read)
class NotificationReadView(APIView):
    permission_classes = [IsAuthenticated]

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
            notification.save(update_fields=['is_read'])

        return Response(
            {
                "id": notification.id,
                "is_read": notification.is_read,
            },
            status=status.HTTP_200_OK
        )