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


class CategoryNormalizeTests(SimpleTestCase):
    def test_keywords_override_generic_category(self):
        from ai.services import normalize_category

        self.assertEqual(normalize_category('기타', '검은색 우산'), '우산')
        self.assertEqual(normalize_category('기타', '검은색 무선 이어폰 케이스'), '이어폰')
        self.assertEqual(normalize_category('카드·신분증', '흰색 가죽 카드 지갑'), '지갑')  # 지갑이 카드보다 먼저
        self.assertEqual(normalize_category('기타', '분홍색 테이크아웃 컵'), '텀블러·물병')
        self.assertEqual(normalize_category('기타', '연보라색 보조배터리'), '전자기기')
        self.assertEqual(normalize_category('기타', '하늘색 노트북 파우치'), '전자기기')  # 노트북이 노트보다 먼저
        self.assertEqual(normalize_category('지갑', None), '지갑')
        self.assertEqual(normalize_category('기타', '이상한 물건'), '기타')

    def test_no_value_strings_become_none(self):
        raw = {
            'is_item': True, 'category': '기타', 'item_name': '검은색 우산', 'color': '없음',
            'brand': 'N/A', 'features': [], 'sensitive': False,
        }
        with mock.patch.object(client, 'chat_json', return_value=raw):
            result = analyze_item_image(b'x')
        self.assertEqual(result.category, '우산')
        self.assertIsNone(result.color)
        self.assertIsNone(result.brand)


class TransparentImageTests(SimpleTestCase):
    def test_transparent_background_becomes_white(self):
        import io as _io

        image = Image.new('RGBA', (40, 40), (0, 0, 0, 0))  # 완전 투명
        for x in range(10, 30):
            for y in range(10, 30):
                image.putpixel((x, y), (0, 0, 0, 255))  # 가운데 검은 물건
        buffer = _io.BytesIO()
        image.save(buffer, format='PNG')
        buffer.seek(0)

        loaded = images.load_image(buffer)
        self.assertEqual(loaded.mode, 'RGB')
        self.assertEqual(loaded.getpixel((2, 2)), (255, 255, 255))  # 배경은 흰색
        self.assertEqual(loaded.getpixel((20, 20)), (0, 0, 0))  # 물건은 그대로


class ExtractKnownFeaturesTests(SimpleTestCase):
    def test_null_like_strings_are_treated_as_unknown(self):
        from ai.services import extract_known_features

        raw = {
            'category': '우산', 'color': '카키색', 'size': 'null', 'material': 'NULL',
            'shape': '접이식', 'marks': '없음', 'brand': ' 알 수 없음 ',
        }
        with mock.patch.object(client, 'chat_json', return_value=raw):
            known = extract_known_features({'category': '우산'}, None)
        self.assertEqual(known, {
            'category': '우산', 'color': '카키색', 'size': None, 'material': None,
            'shape': '접이식', 'marks': None, 'brand': None,
        })


class OwnershipQuestionCountTests(SimpleTestCase):
    def test_returns_one_to_max_questions(self):
        from ai.services import generate_ownership_questions

        one = {'questions': [{'text': '뒷면에 어떤 표시가 있었나요?', 'expected': '빨간 점 3개'}]}
        with mock.patch.object(client, 'chat_json', return_value=one) as chat:
            self.assertEqual(len(generate_ownership_questions({'private_features': 'x'}, {}, max_count=2)), 1)
        self.assertIn('최대 2개', chat.call_args.kwargs['messages'][0]['content'])

        three = {'questions': [{'text': f'q{i}', 'expected': f'e{i}'} for i in range(3)]}
        with mock.patch.object(client, 'chat_json', return_value=three):
            self.assertEqual(len(generate_ownership_questions({}, {}, max_count=2)), 2)

        with mock.patch.object(client, 'chat_json', return_value={'questions': []}):
            with self.assertRaises(AIError):
                generate_ownership_questions({}, {}, max_count=2)
