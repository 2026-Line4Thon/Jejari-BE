from django.db import models

from common.models import BaseModel


class MatchCandidate(BaseModel):
    class Status(models.TextChoices):
        CANDIDATE = 'CANDIDATE', '매칭 후보'
        EXCLUDED = 'EXCLUDED', '후보 제외'
        VERIFYING = 'VERIFYING', '소유권 확인 중'
        MATCHED = 'MATCHED', '소유권 일치'
        MISMATCHED = 'MISMATCHED', '소유권 불일치'
        LOCKED = 'LOCKED', '확인 잠김'

    class SimilarityLabel(models.TextChoices):
        HIGH = 'HIGH', '높은 유사도'
        MEDIUM = 'MEDIUM', '보통 유사도'
        LOW = 'LOW', '낮은 유사도'

    # 아직 진행 중인 후보. MISMATCHED는 남은 시도가 있어 다시 확인할 수 있으므로 진행 중으로 봄
    ACTIVE_STATUSES = (Status.CANDIDATE, Status.VERIFYING, Status.MATCHED, Status.MISMATCHED)
    CLOSED_STATUSES = (Status.EXCLUDED, Status.LOCKED)

    lost_item = models.ForeignKey(
        'items.LostItem',
        on_delete=models.CASCADE,
        related_name='candidates',
    )
    found_item = models.ForeignKey(
        'items.FoundItem',
        on_delete=models.CASCADE,
        related_name='candidates',
    )
    total_score = models.FloatField()  # 내부 정렬용, 화면 응답에 내리지 않음
    similarity_label = models.CharField(max_length=30, choices=SimilarityLabel.choices)
    match_reasons = models.JSONField(default=dict)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.CANDIDATE)
    attempt_count = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['-total_score']
        constraints = [
            models.UniqueConstraint(
                fields=['lost_item', 'found_item'],
                name='uniq_candidate_lost_found',
            ),
        ]
        indexes = [models.Index(fields=['status'])]

    def __str__(self):
        return f'MatchCandidate({self.id}) lost={self.lost_item_id} found={self.found_item_id}'


class OwnershipCheck(BaseModel):
    """소유권 확인 시도 1회 = 1행. 남은 시도 횟수는 같은 후보의 행 수로 계산."""

    class Result(models.TextChoices):
        PENDING = 'PENDING', '답변 대기'
        MATCHED = 'MATCHED', '소유권 일치'
        NEED_MORE = 'NEED_MORE', '추가 확인 필요'
        MISMATCH = 'MISMATCH', '소유권 불일치'

    candidate = models.ForeignKey(
        MatchCandidate,
        on_delete=models.CASCADE,
        related_name='ownership_checks',
    )
    questions = models.JSONField()
    answers = models.JSONField(null=True, blank=True)
    result = models.CharField(max_length=20, choices=Result.choices, default=Result.PENDING)

    class Meta:
        ordering = ['created_at']
