from unittest import mock

from django.core.files.storage import FileSystemStorage
from django.test import SimpleTestCase, override_settings
from storages.backends.s3 import S3Storage

from common.storage import _PrivateStorage, _PublicStorage

S3_SETTINGS = dict(
    USE_S3=True,
    AWS_S3_REGION_NAME='ap-northeast-2',
    AWS_PUBLIC_BUCKET_NAME='jejari-public-test',
    AWS_PRIVATE_BUCKET_NAME='jejari-private-test',
)
FAKE_CREDENTIALS = {'AWS_ACCESS_KEY_ID': 'test', 'AWS_SECRET_ACCESS_KEY': 'test'}


class StorageSelectionTests(SimpleTestCase):
    @override_settings(USE_S3=False, PRIVATE_MEDIA_ROOT='/tmp/jejari-private')
    def test_local_folders_without_s3(self):
        private = _PrivateStorage()
        private._setup()
        self.assertIsInstance(private._wrapped, FileSystemStorage)
        # 비공개 원본은 MEDIA_ROOT(공개 서빙 폴더) 밖에 저장
        self.assertEqual(str(private._wrapped.location).replace('\\', '/').rstrip('/').split(':')[-1], '/tmp/jejari-private')

    @override_settings(**S3_SETTINGS)
    def test_public_bucket_gives_plain_public_url(self):
        public = _PublicStorage()
        public._setup()
        self.assertIsInstance(public._wrapped, S3Storage)
        self.assertEqual(public._wrapped.bucket_name, 'jejari-public-test')
        self.assertFalse(public._wrapped.querystring_auth)
        self.assertTrue(public._wrapped.file_overwrite)  # 저장 전 존재 확인 요청 없음

        with mock.patch.dict('os.environ', FAKE_CREDENTIALS):
            url = public.url('items/abc.jpg')
        self.assertTrue(url.startswith('https://jejari-public-test.s3'))
        self.assertTrue(url.endswith('/items/abc.jpg'))
        self.assertNotIn('Signature', url)
        self.assertNotIn('X-Amz', url)

    @override_settings(**S3_SETTINGS)
    def test_private_bucket_is_separate_and_signed(self):
        private = _PrivateStorage()
        private._setup()
        self.assertIsInstance(private._wrapped, S3Storage)
        self.assertEqual(private._wrapped.bucket_name, 'jejari-private-test')
        self.assertTrue(private._wrapped.querystring_auth)
