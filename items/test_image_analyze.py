import io
import shutil
import tempfile
from unittest import mock

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.utils.functional import empty
from PIL import Image
from rest_framework import status
from rest_framework.test import APITestCase

from ai.services import AIError, ImageAnalysis
from common.storage import private_storage, public_storage
from common.testing import make_user
from items.models import ItemImage

FOUND_URL = '/items/found/images/analyze'
LOST_URL = '/items/lost/images/analyze'


def jpeg_upload(name='photo.jpg', size=(800, 600)):
    buffer = io.BytesIO()
    Image.new('RGB', size, (30, 60, 120)).save(buffer, format='JPEG')
    return SimpleUploadedFile(name, buffer.getvalue(), content_type='image/jpeg')


def analysis(**kwargs):
    data = dict(
        is_item=True, category='이어폰', item_name='무선 이어폰 케이스',
        color='흰색', brand='Apple', features=['모서리 긁힘'], sensitive=False,
    )
    data.update(kwargs)
    return ImageAnalysis(**data)


class ImageAnalyzeAPITests(APITestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.settings_override = override_settings(
            MEDIA_ROOT=f'{self.tmp}/media', PRIVATE_MEDIA_ROOT=f'{self.tmp}/private'
        )
        self.settings_override.enable()
        private_storage._wrapped = empty  # 바뀐 PRIVATE_MEDIA_ROOT로 다시 생성

        self.user = make_user()
        self.client.force_authenticate(self.user)

    def tearDown(self):
        self.settings_override.disable()
        private_storage._wrapped = empty
        shutil.rmtree(self.tmp, ignore_errors=True)

    def post(self, url=FOUND_URL, upload=None, result=None, side_effect=None):
        with mock.patch(
            'items.services.analyze_item_image', return_value=result, side_effect=side_effect
        ) as analyze:
            res = self.client.post(url, {'image': upload or jpeg_upload()}, format='multipart')
        return res, analyze

    def test_success_returns_tags_and_saves_both_images(self):
        res, analyze = self.post(result=analysis(brand=None))

        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        self.assertFalse(res.data['is_blurred'])
        self.assertEqual(res.data['tags']['category'], '이어폰')
        self.assertEqual(res.data['tags']['features'], ['모서리 긁힘'])
        self.assertEqual(res.data['unrecognized_fields'], ['brand'])
        self.assertTrue(res.data['image_url'].startswith('http://testserver/media/items/'))
        analyze.assert_called_once()

        image = ItemImage.objects.get(id=res.data['image_id'])
        self.assertEqual(image.uploader, self.user)
        self.assertEqual(image.ai_tags['item_name'], '무선 이어폰 케이스')
        self.assertTrue(private_storage.exists(image.original_image_key))
        self.assertTrue(public_storage.exists(image.original_image_key))  # 같은 이름, 다른 저장소

        # 비공개 정보는 응답에 없음
        self.assertNotIn('original_image_key', res.data)
        self.assertNotIn('sensitive', res.data['tags'])

    def test_png_is_accepted(self):
        buffer = io.BytesIO()
        Image.new('RGBA', (300, 200), (0, 0, 0, 0)).save(buffer, format='PNG')
        upload = SimpleUploadedFile('p.png', buffer.getvalue(), content_type='image/png')
        res, _ = self.post(upload=upload, result=analysis())
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)

    def test_sensitive_photo_is_blurred(self):
        res, _ = self.post(result=analysis(category='카드·신분증', sensitive=True))
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        self.assertTrue(res.data['is_blurred'])
        self.assertTrue(ItemImage.objects.get(id=res.data['image_id']).is_blurred)

    def test_ai_failure_returns_504_with_screen_specific_message(self):
        res, _ = self.post(url=LOST_URL, side_effect=AIError('timeout'))
        self.assertEqual(res.status_code, status.HTTP_504_GATEWAY_TIMEOUT)
        self.assertEqual(res.data['detail'], '분석 시간이 초과되었습니다. 잠시 후 다시 시도해 주세요.')

        res, _ = self.post(url=FOUND_URL, side_effect=AIError('timeout'))
        self.assertEqual(res.status_code, status.HTTP_504_GATEWAY_TIMEOUT)
        self.assertEqual(res.data['detail'], '분석 시간이 초과되었습니다. 물건 정보를 직접 입력해 주세요.')
        self.assertFalse(ItemImage.objects.exists())

    def test_no_item_returns_422_and_saves_nothing(self):
        res, _ = self.post(result=analysis(is_item=False))
        self.assertEqual(res.status_code, status.HTTP_422_UNPROCESSABLE_ENTITY)
        self.assertEqual(res.data['detail'], '사진에서 물건을 찾지 못했습니다. 다른 사진을 올려 주세요.')
        self.assertFalse(ItemImage.objects.exists())

    def test_lost_url_uses_same_flow(self):
        res, _ = self.post(url=LOST_URL, result=analysis())
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)

    def test_validation_errors(self):
        # 이미지 누락 → 필드 오류
        res = self.client.post(FOUND_URL, {}, format='multipart')
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('image', res.data)

        # 이미지가 아님 / jpg·png가 아님 / 용량 초과 → detail 메시지
        expected = 'jpg, png 형식의 10MB 이하 이미지만 업로드할 수 있습니다.'
        res, analyze = self.post(
            upload=SimpleUploadedFile('a.txt', b'hello', content_type='text/plain')
        )
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(res.data['detail'], expected)
        analyze.assert_not_called()

        buffer = io.BytesIO()
        Image.new('RGB', (50, 50)).save(buffer, format='GIF')
        res, analyze = self.post(
            upload=SimpleUploadedFile('a.gif', buffer.getvalue(), content_type='image/gif')
        )
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        analyze.assert_not_called()

        with override_settings(IMAGE_MAX_UPLOAD_MB=0):
            res, analyze = self.post(result=analysis())
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        analyze.assert_not_called()

    def test_requires_login(self):
        self.client.force_authenticate(None)
        res = self.client.post(FOUND_URL, {'image': jpeg_upload()}, format='multipart')
        self.assertEqual(res.status_code, status.HTTP_401_UNAUTHORIZED)
