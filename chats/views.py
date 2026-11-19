from django.db import transaction
from django.utils import timezone
from django.core.paginator import Paginator
from rest_framework import status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from drf_spectacular.utils import extend_schema, OpenApiParameter, OpenApiTypes

from matching.models import MatchCandidate
from matching.services import complete_return
from .models import ChatRoom, ChatMessage
from .services import create_chat_room
from .serializers import (
    ChatRoomCreateSerializer,
    ChatRoomResponseSerializer,
    ChatMessageSerializer,
    ChatMessageCreateSerializer,
)


class ChatRoomCreateView(APIView):
    """1. 비공개 채팅방 생성 (POST /chats)"""
    permission_classes = [IsAuthenticated]

    @extend_schema(
        summary="비공개 채팅방 생성",
        request=ChatRoomCreateSerializer,
        responses={200: ChatRoomResponseSerializer},
        tags=["G. 채팅 및 반환"],
    )
    @transaction.atomic
    def post(self, request):
        serializer = ChatRoomCreateSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        candidate_id = serializer.validated_data['candidate_id']

        try:
            candidate = MatchCandidate.objects.select_related(
                'lost_item__user', 'found_item__finder'
            ).get(id=candidate_id)
        except MatchCandidate.DoesNotExist:
            return Response(
                {"detail": "해당 매칭 후보 정보를 찾을 수 없습니다."},
                status=status.HTTP_404_NOT_FOUND
            )

        # 소유권 확인이 일치(MATCHED)한 후보만 채팅방 생성 가능
        if candidate.status != MatchCandidate.Status.MATCHED:
            return Response(
                {"detail": "소유권 확인이 완료되지 않아 채팅방을 생성할 수 없습니다."},
                status=status.HTTP_403_FORBIDDEN
            )

        owner = candidate.lost_item.user
        finder = candidate.found_item.finder

        if request.user not in (owner, finder):
            return Response(
                {"detail": "소유권 확인이 완료되지 않아 채팅방을 생성할 수 없습니다."},
                status=status.HTTP_403_FORBIDDEN
            )

        chat_room, _ = create_chat_room(candidate)

        res_serializer = ChatRoomResponseSerializer(chat_room, context={'request': request})
        return Response(res_serializer.data, status=status.HTTP_200_OK)


class ChatMessageListCreateView(APIView):
    """
    2. 채팅 메시지 목록 조회 (GET /chats/<int:chat_id>/messages)
    3. 채팅 메시지 전송 (POST /chats/<int:chat_id>/messages)
    """
    permission_classes = [IsAuthenticated]

    def get_chat_room(self, chat_id):
        try:
            return ChatRoom.objects.select_related('candidate__found_item__image').get(id=chat_id)
        except ChatRoom.DoesNotExist:
            return None

    @extend_schema(
        summary="채팅 메시지 목록 조회",
        parameters=[
            OpenApiParameter(
                name='page',
                type=OpenApiTypes.INT,
                location=OpenApiParameter.QUERY,
                required=False,
                default=1,
                description="페이지 번호 (기본값: 1)",
            ),
            OpenApiParameter(
                name='size',
                type=OpenApiTypes.INT,
                location=OpenApiParameter.QUERY,
                required=False,
                default=30,
                description="페이지당 메시지 개수 (기본값: 30)",
            ),
        ],
        responses={200: OpenApiTypes.OBJECT},
        tags=["G. 채팅 및 반환"],
    )
    def get(self, request, chat_id):
        chat_room = self.get_chat_room(chat_id)
        if not chat_room:
            return Response(
                {"detail": "채팅방을 찾을 수 없습니다."},
                status=status.HTTP_404_NOT_FOUND
            )

        if not chat_room.is_participant(request.user):
            return Response(
                {"detail": "해당 채팅방에 접근할 권한이 없습니다."},
                status=status.HTTP_403_FORBIDDEN
            )

        # 상대방이 보낸 안 읽은 메시지 일괄 읽음 처리
        chat_room.messages.exclude(sender=request.user).filter(is_read=False).update(is_read=True)

        try:
            page = max(1, int(request.query_params.get('page', 1)))
            size = max(1, int(request.query_params.get('size', 30)))
        except ValueError:
            page, size = 1, 30

        queryset = chat_room.messages.select_related('sender').order_by('created_at')
        paginator = Paginator(queryset, size)
        page_obj = paginator.get_page(page)

        msg_serializer = ChatMessageSerializer(
            page_obj.object_list, many=True, context={'request': request}
        )
        found_item = chat_room.candidate.found_item
        full_name = f"{found_item.color} {found_item.item_name}".strip() if found_item.color else found_item.item_name

        return Response({
            "chat_room_id": chat_room.id,
            "status": chat_room.status,
            "item_summary": {
                "item_name": full_name,
                "blurred_image_url": found_item.image.image_url if found_item.image else None,
            },
            "messages": msg_serializer.data
        }, status=status.HTTP_200_OK)

    @extend_schema(
        summary="채팅 메시지 전송",
        request=ChatMessageCreateSerializer,
        responses={200: OpenApiTypes.OBJECT},
        tags=["G. 채팅 및 반환"],
    )
    def post(self, request, chat_id):
        chat_room = self.get_chat_room(chat_id)
        if not chat_room:
            return Response(
                {"detail": "채팅방을 찾을 수 없습니다."},
                status=status.HTTP_404_NOT_FOUND
            )

        if not chat_room.is_participant(request.user):
            return Response(
                {"detail": "해당 채팅방에 메시지를 전송할 권한이 없습니다."},
                status=status.HTTP_403_FORBIDDEN
            )

        if chat_room.status == 'COMPLETED':
            return Response(
                {"detail": "반환이 완료된 채팅방에는 메시지를 보낼 수 없습니다."},
                status=status.HTTP_400_BAD_REQUEST
            )

        serializer = ChatMessageCreateSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        message = ChatMessage.objects.create(
            chat_room=chat_room,
            sender=request.user,
            content=serializer.validated_data['content']
        )

        return Response({
            "message_id": message.id,
            "chat_room_id": chat_room.id,
            "sender_id": request.user.id,
            "content": message.content,
            "created_at": message.created_at
        }, status=status.HTTP_200_OK)


class ChatCompleteView(APIView):
    """4. 반환 완료 처리 (POST /chats/<int:chat_id>/complete)"""
    permission_classes = [IsAuthenticated]

    @extend_schema(
        summary="물품 반환 완료 처리",
        request=None,
        responses={200: OpenApiTypes.OBJECT},
        tags=["G. 채팅 및 반환"],
    )
    @transaction.atomic
    def post(self, request, chat_id):
        try:
            chat_room = ChatRoom.objects.select_for_update().select_related(
                'candidate__lost_item', 'candidate__found_item'
            ).get(id=chat_id)
        except ChatRoom.DoesNotExist:
            return Response(
                {"detail": "채팅방을 찾을 수 없습니다."},
                status=status.HTTP_404_NOT_FOUND
            )

        if not chat_room.is_participant(request.user):
            return Response(
                {"detail": "해당 거래를 완료 처리할 권한이 없습니다."},
                status=status.HTTP_403_FORBIDDEN
            )

        if chat_room.status == 'COMPLETED':
            return Response(
                {"detail": "이미 반환 완료 처리된 거래입니다."},
                status=status.HTTP_400_BAD_REQUEST
            )

        now = timezone.now()

        # 1. 채팅방 상태 완료 처리
        chat_room.status = 'COMPLETED'
        chat_room.completed_at = now
        chat_room.save(update_fields=['status', 'completed_at', 'updated_at'])

        # 2. 분실물·습득물 COMPLETED 전환 + 같은 물건에 걸린 다른 후보 종료
        lost_item, found_item = complete_return(chat_room.candidate)

        return Response({
            "chat_room_id": chat_room.id,
            "status": chat_room.status,
            "lost_item_status": lost_item.status,
            "found_item_status": found_item.status,
            "completed_at": chat_room.completed_at,
            "message": "물품 반환이 완료 처리되었습니다."
        }, status=status.HTTP_200_OK)