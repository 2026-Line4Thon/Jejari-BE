"""
공개용 / 비공개 원본 저장소 분리.

- 공개용(블러 반영본): public_storage → 화면에 보여 줄 URL로 서빙
- 비공개 원본: private_storage → URL로 공개하지 않음 (소유권 확인·재분석 등 서버 내부에서만 사용)

배포(USE_S3=True): 버킷 두 개로 분리
  - 공개용  AWS_PUBLIC_BUCKET_NAME  (버킷 정책으로 공개 읽기 허용, URL에 서명 없음)
  - 비공개  AWS_PRIVATE_BUCKET_NAME (퍼블릭 액세스 전면 차단)
  자격 증명은 컨테이너 환경변수 AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY 를 boto3가 읽습니다.
로컬·테스트(USE_S3=False): MEDIA_ROOT / PRIVATE_MEDIA_ROOT 폴더
"""

from django.conf import settings
from django.core.files.storage import FileSystemStorage, default_storage
from django.utils.functional import LazyObject


def _s3_storage(bucket_name, public):
    from storages.backends.s3 import S3Storage

    return S3Storage(
        bucket_name=bucket_name,
        region_name=settings.AWS_S3_REGION_NAME,
        # 공개 버킷은 버킷 정책으로 읽기를 허용하므로 서명 없는 고정 URL, 비공개는 서명 URL만
        querystring_auth=not public,
        default_acl=None,  # 객체 ACL 대신 버킷 정책 사용 (ACL 비활성 버킷에서도 동작)
        # 파일 이름은 매번 uuid라 겹치지 않으므로, 저장 전 존재 확인(HeadObject) 요청을 하지 않음
        # → IAM 키에 조회 권한이 없어도 업로드(PutObject)만으로 동작
        file_overwrite=True,
        object_parameters={'CacheControl': 'max-age=86400'} if public else {},
    )


class _PublicStorage(LazyObject):
    def _setup(self):
        if settings.USE_S3:
            self._wrapped = _s3_storage(settings.AWS_PUBLIC_BUCKET_NAME, public=True)
        else:
            self._wrapped = default_storage  # MEDIA_ROOT, MEDIA_URL


class _PrivateStorage(LazyObject):
    def _setup(self):
        if settings.USE_S3:
            self._wrapped = _s3_storage(settings.AWS_PRIVATE_BUCKET_NAME, public=False)
        else:
            self._wrapped = FileSystemStorage(location=settings.PRIVATE_MEDIA_ROOT, base_url=None)


public_storage = _PublicStorage()
private_storage = _PrivateStorage()
