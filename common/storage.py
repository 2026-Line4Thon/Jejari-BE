"""
공개용 / 비공개 원본 저장소 분리.

- 공개용(블러 반영본): default_storage → MEDIA_ROOT, URL로 서빙됨
- 비공개 원본: private_storage → PRIVATE_MEDIA_ROOT, URL로 서빙하지 않음
  (소유권 확인·재분석 등 서버 내부에서만 사용)

배포 시 S3로 바꿀 때는 이 두 저장소만 S3 버킷/경로로 교체하면 됩니다.
"""

from django.conf import settings
from django.core.files.storage import FileSystemStorage, default_storage
from django.utils.functional import LazyObject


class _PrivateStorage(LazyObject):
    def _setup(self):
        self._wrapped = FileSystemStorage(location=settings.PRIVATE_MEDIA_ROOT, base_url=None)


public_storage = default_storage
private_storage = _PrivateStorage()
