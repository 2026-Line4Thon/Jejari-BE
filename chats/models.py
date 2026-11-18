from django.conf import settings
from django.db import models

from common.models import BaseModel


class ChatRoom(BaseModel):
    class Status(models.TextChoices):
        ACTIVE = 'ACTIVE', '진행 중'
        COMPLETED = 'COMPLETED', '반환 완료'

    candidate = models.OneToOneField(
        'matching.MatchCandidate',
        on_delete=models.CASCADE,
        related_name='chat_room'
    )
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='owner_chats'
    )
    finder = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='finder_chats'
    )
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.ACTIVE)
    completed_at = models.DateTimeField(null=True, blank=True)

    def is_participant(self, user):
        return user == self.owner or user == self.finder


class ChatMessage(BaseModel):
    chat_room = models.ForeignKey(
        ChatRoom,
        on_delete=models.CASCADE,
        related_name='messages'
    )
    sender = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE
    )
    content = models.TextField()
    is_read = models.BooleanField(default=False)

    class Meta:
        ordering = ['created_at']
