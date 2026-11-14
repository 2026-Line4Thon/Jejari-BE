from django.db import migrations
from pgvector.django import VectorExtension


class Migration(migrations.Migration):
    """pgvector 확장 활성화. VectorField를 쓰는 앱의 첫 마이그레이션은 이것에 의존해야 함."""

    initial = True

    dependencies = []

    operations = [
        VectorExtension(),
    ]
