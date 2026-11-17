from django.db import models
from django.conf import settings
from items.models import MatchCandidate


class ChatRoom(models.Model):
    STATUS_CHOICES = (
        ('ACTIVE', '진행 중'),
        ('COMPLETED', '반환 완료'),
    )
    candidate = models.OneToOneField(
        MatchCandidate,
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
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='ACTIVE')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    def is_participant(self, user):
        return user == self.owner or user == self.finder


class ChatMessage(models.Model):
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
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['created_at']