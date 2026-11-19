from unittest import mock

from django.test import SimpleTestCase, override_settings
from PIL import Image

from ai import client, images
from ai.services import AIError, analyze_item_image


class AnalyzeItemImageTests(SimpleTestCase):
    def _run(self, raw):
        with mock.patch.object(client, 'chat_json', return_value=raw) as chat_json:
            result = analyze_item_image(b'fake-jpeg')
        return result, chat_json

    def test_parses_and_cleans_response(self):
        result, chat_json = self._run({
            'is_item': True,
            'category': '이어폰',
            'item_name': '  무선 이어폰 케이스 ',
            'color': '흰색',
            'brand': '',
            'features': ['모서리 긁힘', ' ', '고양이 스티커', 'a', 'b', 'c', 'd'],
            'sensitive': False,
        })
        self.assertTrue(result.is_item)
        self.assertEqual(result.item_name, '무선 이어폰 케이스')
        self.assertIsNone(result.brand)  # 빈 문자열 → None
        self.assertEqual(result.features, ['모서리 긁힘', '고양이 스티커', 'a', 'b', 'c'])  # 최대 5개

        # 사진은 data URL로, JSON 스키마는 strict로 전달
        kwargs = chat_json.call_args.kwargs
        image_part = kwargs['messages'][1]['content'][1]
        self.assertTrue(image_part['image_url']['url'].startswith('data:image/jpeg;base64,'))
        self.assertEqual(kwargs['schema_name'], 'item_image_analysis')

    def test_no_item(self):
        result, _ = self._run({
            'is_item': False, 'category': None, 'item_name': None, 'color': None,
            'brand': None, 'features': [], 'sensitive': False,
        })
        self.assertFalse(result.is_item)

    def test_malformed_response_raises(self):
        with self.assertRaises(AIError):
            self._run({'category': '지갑'})

    @override_settings(OPENAI_API_KEY='')
    def test_missing_api_key_raises(self):
        with self.assertRaises(AIError):
            client.get_client()


class ImageProcessingTests(SimpleTestCase):
    def test_blur_changes_pixels_and_keeps_size(self):
        image = Image.new('RGB', (200, 100), 'white')
        for x in range(0, 200, 2):
            for y in range(100):
                image.putpixel((x, y), (0, 0, 0))
        blurred = images.blur(image)
        self.assertEqual(blurred.size, image.size)
        self.assertNotEqual(blurred.getpixel((10, 50)), image.getpixel((10, 50)))

    def test_to_jpeg_resizes(self):
        image = Image.new('RGB', (4000, 2000), 'red')
        data = images.to_jpeg_bytes(image, max_side=1000)
        import io
        self.assertEqual(Image.open(io.BytesIO(data)).size, (1000, 500))

    def test_invalid_image(self):
        import io
        with self.assertRaises(images.InvalidImage):
            images.load_image(io.BytesIO(b'not an image'))


class PersonalInfoFilterTests(SimpleTestCase):
    def test_features_with_personal_info_are_dropped(self):
        raw = {
            'is_item': True, 'category': '카드·신분증', 'item_name': '학생증', 'color': None,
            'brand': None, 'sensitive': True,
            'features': [
                '학과: 컴퓨터 사이언스', '학생 번호: 20231234', '010-1234-5678',
                '이름 홍길동', '파란 띠 디자인', '사진 부착',
            ],
        }
        with mock.patch.object(client, 'chat_json', return_value=raw):
            result = analyze_item_image(b'fake-jpeg')
        self.assertEqual(result.features, ['파란 띠 디자인', '사진 부착'])


class SummarizeItemTests(SimpleTestCase):
    def test_sends_only_filled_fields_and_returns_summary(self):
        from ai.services import summarize_item

        with mock.patch.object(client, 'chat_json', return_value={'summary': ' 검은색 지갑입니다. '}) as chat:
            result = summarize_item({'category': '지갑', 'color': None, 'features': [], 'detail': '학생증'})
        self.assertEqual(result, '검은색 지갑입니다.')
        user_message = chat.call_args.kwargs['messages'][1]['content']
        self.assertIn('학생증', user_message)
        self.assertNotIn('color', user_message)

    def test_empty_summary_raises(self):
        from ai.services import summarize_item

        with mock.patch.object(client, 'chat_json', return_value={'summary': ' '}):
            with self.assertRaises(AIError):
                summarize_item({'category': '지갑'})
