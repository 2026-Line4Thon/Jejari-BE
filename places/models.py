from django.db import models

from common.models import BaseModel


class Place(BaseModel):
    """캠퍼스 건물·장소 마스터 (A 담당, ERD v2.0 컬럼 기준 최소 형태)."""

    name = models.CharField(max_length=100, unique=True)  # 예: 중앙도서관
    latitude = models.DecimalField(max_digits=10, decimal_places=7)
    longitude = models.DecimalField(max_digits=10, decimal_places=7)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name
