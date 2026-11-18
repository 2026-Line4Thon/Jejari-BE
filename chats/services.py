"""
채팅방 생성 함수.

소유권 확인 결과가 MATCHED일 때 create_chat_room()을 호출하고,
반환된 chat_room.id를 응답의 chat_room_id로 내려줍니다.
"""

from django.db import transaction

from items.models import ItemStatus
from notifications.models import Notification
from notifications import services as notification_services

from .models import ChatRoom


@transaction.atomic
def create_chat_room(candidate):
    """MATCHED 후보의 채팅방을 만들고 (chat_room, created)를 반환. 이미 있으면 기존 방 반환."""
    owner = candidate.lost_item.user
    finder = candidate.found_item.finder

    chat_room, created = ChatRoom.objects.get_or_create(
        candidate=candidate,
        defaults={'owner': owner, 'finder': finder, 'status': ChatRoom.Status.ACTIVE},
    )

    if created:
        for item in (candidate.lost_item, candidate.found_item):
            if item.status != ItemStatus.COMPLETED:
                item.status = ItemStatus.CHATTING
                item.save(update_fields=['status', 'updated_at'])

        for target_user in (owner, finder):
            notification_services.send(
                user=target_user,
                type=Notification.Type.CHAT_STARTED,
                target_type=Notification.TargetType.CHAT_ROOM,
                target_id=chat_room.id,
            )

    return chat_room, created
