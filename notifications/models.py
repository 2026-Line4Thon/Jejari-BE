from django.conf import settings
from django.db import models

from common.models import BaseModel


class Notification(BaseModel):
    class Type(models.TextChoices):
        MATCH_CANDIDATE = 'MATCH_CANDIDATE', '새 매칭 후보'
        OWNERSHIP_RESULT = 'OWNERSHIP_RESULT', '소유권 확인 결과'
        CHAT_STARTED = 'CHAT_STARTED', '채팅 시작'

    class TargetType(models.TextChoices):
        CANDIDATE = 'CANDIDATE', '매칭 후보'
        CHAT_ROOM = 'CHAT_ROOM', '채팅방'

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='notifications',
    )
    type = models.CharField(max_length=30, choices=Type.choices)
    target_type = models.CharField(max_length=20, choices=TargetType.choices)
    target_id = models.BigIntegerField()  # 클릭 시 이동할 candidate_id 또는 chat_room_id
    title = models.CharField(max_length=150)
    message = models.TextField()
    is_read = models.BooleanField(default=False)

    class Meta:
        ordering = ['-created_at']
