from unittest import mock

from rest_framework import status
from rest_framework.test import APITestCase

from ai.services import AIError
from common.testing import (
    make_candidate,
    make_found_item,
    make_image,
    make_lost_item,
    make_place,
    make_user,
    zero_vector,
)
from items.models import FeatureChat, LostItem
from matching.models import MatchCandidate

URL = '/items/lost'


class LostItemCreateAPITests(APITestCase):
    def setUp(self):
        self.user = make_user()
        self.client.force_authenticate(self.user)
        self.place = make_place(name='중앙도서관')
        self.image = make_image(self.user)
        self.vector = zero_vector()
        self.vector[0] = 1.0

        patches = {
            'summarize': mock.patch(
                'items.services.summarize_item',
                return_value='검은색 가죽 반지갑으로, 모서리가 해져 있고 학생증이 들어 있습니다.',
            ),
            'embed': mock.patch('items.services.embed_text', return_value=self.vector),
            'schedule': mock.patch('items.services.schedule_matching'),
        }
        self.mocks = {name: p.start() for name, p in patches.items()}
        for p in patches.values():
            self.addCleanup(p.stop)

    def payload(self, **overrides):
        data = {
            'image_id': self.image.id,
            'category': '지갑',
            'item_name': '검은색 가죽 반지갑',
            'color': '검정',
            'brand': None,
            'features': ['가죽 재질', '모서리 해짐'],
            'description': '학생증이 들어 있어요.',
            'place_id': self.place.id,
            'location_detail': '3층 열람실',
            'lost_from': '2026-11-13T13:00:00+09:00',
            'lost_to': '2026-11-13T15:00:00+09:00',
        }
        data.update(overrides)
        return {k: v for k, v in data.items() if v is not ...}

    def test_register_with_photo(self):
        res = self.client.post(URL, self.payload(), format='json')

        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        self.assertEqual(res.data['status'], 'WAITING')
        self.assertEqual(res.data['message'], '분실물이 등록되었습니다. 비슷한 물건을 찾고 있어요.')

        item = LostItem.objects.get(id=res.data['lost_item_id'])
        self.assertEqual(item.user, self.user)
        self.assertEqual(item.image, self.image)
        self.assertEqual(item.place, self.place)
        self.assertEqual(item.features, ['가죽 재질', '모서리 해짐'])
        self.assertEqual(item.description, '검은색 가죽 반지갑으로, 모서리가 해져 있고 학생증이 들어 있습니다.')
        self.assertEqual(item.text_embedding[0], 1.0)

        # 사용자 상세 설명이 설명문 생성 입력에 들어가고, 임베딩은 설명문으로 생성
        info = self.mocks['summarize'].call_args.args[0]
        self.assertEqual(info['detail'], '학생증이 들어 있어요.')
        self.mocks['embed'].assert_called_once_with(item.description)
        self.mocks['schedule'].assert_called_once_with('lost', item.id)

    def test_register_text_only_and_default_lost_to(self):
        res = self.client.post(
            URL, self.payload(image_id=..., lost_to=..., color=''), format='json'
        )
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        item = LostItem.objects.get(id=res.data['lost_item_id'])
        self.assertIsNone(item.image)
        self.assertIsNone(item.color)  # 빈 문자열 → null
        self.assertEqual(item.lost_to, item.lost_from)

    def test_photo_and_description_both_missing(self):
        res = self.client.post(URL, self.payload(image_id=None, description=''), format='json')
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(res.data['detail'], '사진 또는 물건 설명 중 하나 이상을 입력해 주세요.')

    def test_time_range_error(self):
        res = self.client.post(
            URL,
            self.payload(lost_from='2026-11-13T16:00:00+09:00', lost_to='2026-11-13T15:00:00+09:00'),
            format='json',
        )
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(res.data['detail'], '분실 시작 시각은 끝 시각보다 앞서야 합니다.')

    def test_required_fields(self):
        res = self.client.post(URL, self.payload(category=..., place_id=...), format='json')
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('category', res.data)
        self.assertIn('place_id', res.data)
        self.assertFalse(LostItem.objects.exists())

    def test_unknown_or_foreign_image_and_place(self):
        others_image = make_image(make_user())
        for overrides in ({'image_id': others_image.id}, {'image_id': 999999}, {'place_id': 999999}):
            res = self.client.post(URL, self.payload(**overrides), format='json')
            self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND, overrides)
            self.assertEqual(res.data['detail'], '이미지 또는 장소를 찾을 수 없습니다.')
        self.assertFalse(LostItem.objects.exists())

    def test_summary_failure_falls_back_to_template(self):
        self.mocks['summarize'].side_effect = AIError('timeout')
        res = self.client.post(URL, self.payload(), format='json')
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        item = LostItem.objects.get(id=res.data['lost_item_id'])
        self.assertIn('검은색 가죽 반지갑', item.description)
        self.assertIn('학생증이 들어 있어요.', item.description)

    def test_embedding_failure_returns_504_and_saves_nothing(self):
        self.mocks['embed'].side_effect = AIError('timeout')
        res = self.client.post(URL, self.payload(), format='json')
        self.assertEqual(res.status_code, status.HTTP_504_GATEWAY_TIMEOUT)
        self.assertFalse(LostItem.objects.exists())
        self.mocks['schedule'].assert_not_called()

    def test_feature_chat_is_linked_and_summary_used(self):
        chat = FeatureChat.objects.create(user=self.user, summary='안쪽에 고양이 스티커가 있음', is_finished=True)
        res = self.client.post(URL, self.payload(feature_chat_id=chat.id), format='json')
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        chat.refresh_from_db()
        self.assertEqual(chat.lost_item_id, res.data['lost_item_id'])
        self.assertEqual(self.mocks['summarize'].call_args.args[0]['chat_summary'], '안쪽에 고양이 스티커가 있음')

        others_chat = FeatureChat.objects.create(user=make_user())
        res = self.client.post(URL, self.payload(feature_chat_id=others_chat.id), format='json')
        self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND)

    def test_requires_login(self):
        self.client.force_authenticate(None)
        res = self.client.post(URL, self.payload(), format='json')
        self.assertEqual(res.status_code, status.HTTP_401_UNAUTHORIZED)


class LostItemDetailAPITests(APITestCase):
    def setUp(self):
        self.user = make_user()
        self.client.force_authenticate(self.user)
        self.place = make_place(name='중앙도서관')
        self.item = make_lost_item(
            self.user,
            place=self.place,
            image=make_image(self.user, image_url='/media/items/a.jpg'),
            category='지갑',
            item_name='검은색 가죽 반지갑',
            features=['가죽 재질'],
            description='검은색 가죽 반지갑입니다.',
            location_detail='3층 열람실',
            status='CANDIDATE_FOUND',
        )
        finder = make_user()
        make_candidate(self.item, make_found_item(finder), status=MatchCandidate.Status.CANDIDATE)
        make_candidate(self.item, make_found_item(finder), status=MatchCandidate.Status.VERIFYING)
        make_candidate(self.item, make_found_item(finder), status=MatchCandidate.Status.EXCLUDED)

    def test_detail(self):
        res = self.client.get(f'{URL}/{self.item.id}')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data['lost_item_id'], self.item.id)
        self.assertEqual(res.data['image_url'], 'http://testserver/media/items/a.jpg')
        self.assertEqual(res.data['summary'], '검은색 가죽 반지갑입니다.')
        self.assertEqual(res.data['place'], {'place_id': self.place.id, 'name': '중앙도서관'})
        self.assertEqual(res.data['status'], 'CANDIDATE_FOUND')
        self.assertEqual(res.data['candidate_count'], 2)  # 제외된 후보는 빼고 셈
        self.assertNotIn('text_embedding', res.data)

    def test_text_only_item_has_null_image_url(self):
        item = make_lost_item(self.user)
        res = self.client.get(f'{URL}/{item.id}')
        self.assertIsNone(res.data['image_url'])

    def test_other_users_item_is_forbidden(self):
        other = make_lost_item(make_user())
        res = self.client.get(f'{URL}/{other.id}')
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)

    def test_not_found(self):
        res = self.client.get(f'{URL}/999999')
        self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(res.data['detail'], '분실물을 찾을 수 없습니다.')
