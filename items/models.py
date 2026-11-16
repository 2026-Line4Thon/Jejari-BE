from django.db import models

# Create your models here.

from django.conf import settings


class FoundItem(models.Model):
    STATUS_CHOICES = (
        ('REGISTERED', '등록됨'),
        ('MATCHING', '매칭중'),
        ('COMPLETED', '반환완료'),
    )

    finder = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='found_items'
    )
    category = models.CharField(max_length=100)          # 예: "전자기기"
    item_name = models.CharField(max_length=100)         # 예: "무선 이어폰 케이스"
    color = models.CharField(max_length=50, blank=True)  # 예: "검정색"
    brand = models.CharField(max_length=50, blank=True)  # 예: "Apple"
    found_location = models.CharField(max_length=100)    # 예: "중앙도서관 2층 열람실"
    found_at = models.DateTimeField()                    # 습득 일시
    storage_status = models.CharField(max_length=50, default='직접 보관 중')
    original_image_url = models.URLField()
    blurred_image_url = models.URLField()                # 공개용 블러 이미지 URL
    private_features = models.TextField(blank=True)      # 비공개 특징 (상세/목록 미노출)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='REGISTERED')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']


class LostItem(models.Model):
    STATUS_CHOICES = (
        ('WAITING', '매칭대기'),
        ('CANDIDATE_FOUND', '후보있음'),
        ('VERIFYING', '소유권확인중'),
        ('CHATTING', '채팅중'),
        ('COMPLETED', '반환완료'),
    )

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='lost_items'
    )
    item_name = models.CharField(max_length=100)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='WAITING')
    created_at = models.DateTimeField(auto_now_add=True)


class MatchCandidate(models.Model):
    STATUS_CHOICES = (
        ('PENDING', '확인대기'),
        ('REJECTED', '후보제외'),
        ('VERIFIED', '소유권일치'),
        ('COMPLETED', '반환완료'),
    )

    lost_item = models.ForeignKey(LostItem, on_delete=models.CASCADE, related_name='candidates')
    found_item = models.ForeignKey(FoundItem, on_delete=models.CASCADE, related_name='candidates')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='PENDING')
    created_at = models.DateTimeField(auto_now_add=True)


class Notification(models.Model):
    TYPE_CHOICES = (
        ('MATCH_CANDIDATE', '새 매칭 후보'),
        ('OWNERSHIP_RESULT', '소유권 확인 결과'),
        ('CHAT_STARTED', '채팅 시작'),
    )

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='notifications'
    )
    type = models.CharField(max_length=30, choices=TYPE_CHOICES)
    title = models.CharField(max_length=150)
    message = models.TextField()
    target_id = models.BigIntegerField()  # 클릭 시 이동할 candidate_id 또는 chat_room_id
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']