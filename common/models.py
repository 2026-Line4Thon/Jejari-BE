from django.db import models


class BaseModel(models.Model):
    """모든 모델이 상속하는 공통 타임스탬프 모델."""

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True
