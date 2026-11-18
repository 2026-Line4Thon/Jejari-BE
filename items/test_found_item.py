from datetime import timedelta
from unittest import mock

from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from ai.services import AIError
from common.testing import make_image, make_place, make_user, zero_vector
from items.models import FoundItem

URL = '/items/found'


class FoundItemCreateAPITests(APITestCase):
    def setUp(self):
        self.user = make_user()
        self.client.force_authenticate(self.user)
        self.place = make_place(name='중앙도서관')
        self.image = make_image(self.user, is_blurred=True)

        patches = {
            'summarize': mock.patch(
                'items.services.summarize_item',
                return_value='남색 가죽 카드지갑으로, 학생증이 들어 있습니다.',
            ),
            'embed': mock.patch('items.services.embed_text', return_value=zero_vector()),
            'schedule': mock.patch('items.services.schedule_matching'),
        }
        self.mocks = {name: p.start() for name, p in patches.items()}
        for p in patches.values():
            self.addCleanup(p.stop)

    def payload(self, **overrides):
        data = {
            'image_id': self.image.id,
            'category': '카드지갑',
            'item_name': '남색 가죽 카드지갑',
            'color': '남색',
            'brand': None,
            'features': ['학생증 포함', '가죽 재질'],
            'description': '열람실 책상 위에 있었어요.',
            'place_id': self.place.id,
            'location_detail': '3층 열람실',
            'found_at': (timezone.now() - timedelta(hours=1)).isoformat(),
            'storage_status': 'HANDED_OVER',
            'storage_location': '중앙도서관 1층 안내데스크',
            'private_features': '안쪽 포켓에 고양이 스티커가 붙어 있음',
        }
        data.update(overrides)
        return {k: v for k, v in data.items() if v is not ...}

    def test_register(self):
        res = self.client.post(URL, self.payload(), format='json')

        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        self.assertEqual(res.data['status'], 'WAITING')
        self.assertEqual(res.data['message'], '습득물이 등록되었습니다. 주인을 찾고 있어요.')

        item = FoundItem.objects.get(id=res.data['found_item_id'])
        self.assertEqual(item.finder, self.user)
        self.assertEqual(item.image, self.image)
        self.assertEqual(item.storage_status, 'HANDED_OVER')
        self.assertEqual(item.storage_location, '중앙도서관 1층 안내데스크')
        self.assertEqual(item.private_features, '안쪽 포켓에 고양이 스티커가 붙어 있음')
        self.assertEqual(item.description, '남색 가죽 카드지갑으로, 학생증이 들어 있습니다.')
        self.mocks['schedule'].assert_called_once_with('found', item.id)

    def test_private_features_never_reach_public_summary(self):
        self.client.post(URL, self.payload(), format='json')
        info = self.mocks['summarize'].call_args.args[0]
        self.assertNotIn('고양이 스티커', str(info))

    def test_self_storage_clears_storage_location(self):
        res = self.client.post(
            URL, self.payload(storage_status='SELF', storage_location='무시됨'), format='json'
        )
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        self.assertIsNone(FoundItem.objects.get(id=res.data['found_item_id']).storage_location)

    def test_handed_over_requires_storage_location(self):
        res = self.client.post(URL, self.payload(storage_location=''), format='json')
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(res.data, {'storage_location': ['인계한 경우 보관 장소를 입력해 주세요.']})

    def test_future_found_at(self):
        future = (timezone.now() + timedelta(hours=1)).isoformat()
        res = self.client.post(URL, self.payload(found_at=future), format='json')
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(res.data, {'found_at': ['습득 시각은 현재보다 이후일 수 없습니다.']})

    def test_required_fields(self):
        res = self.client.post(
            URL, self.payload(category=..., found_at=..., image_id=..., storage_status=...),
            format='json',
        )
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        for field in ('category', 'found_at', 'image_id', 'storage_status'):
            self.assertIn(field, res.data)

        res = self.client.post(URL, self.payload(storage_status='LOST'), format='json')
        self.assertIn('storage_status', res.data)
        self.assertFalse(FoundItem.objects.exists())

    def test_unknown_or_foreign_image_and_place(self):
        for overrides in (
            {'image_id': make_image(make_user()).id}, {'image_id': 999999}, {'place_id': 999999},
        ):
            res = self.client.post(URL, self.payload(**overrides), format='json')
            self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND, overrides)
            self.assertEqual(res.data['detail'], '이미지 또는 장소를 찾을 수 없습니다.')
        self.assertFalse(FoundItem.objects.exists())

    def test_embedding_failure_returns_504(self):
        self.mocks['embed'].side_effect = AIError('timeout')
        res = self.client.post(URL, self.payload(), format='json')
        self.assertEqual(res.status_code, status.HTTP_504_GATEWAY_TIMEOUT)
        self.assertFalse(FoundItem.objects.exists())

    def test_registered_item_appears_in_list_without_private_fields(self):
        self.client.post(URL, self.payload(), format='json')
        res = self.client.get(f'{URL}?page=1&size=10')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data['total_count'], 1)
        card = res.data['items'][0]
        self.assertEqual(card['found_location'], '중앙도서관 3층 열람실')
        self.assertNotIn('private_features', card)

        detail = self.client.get(f"{URL}/{card['id']}")
        self.assertNotIn('private_features', detail.data)
        self.assertNotIn('고양이', str(detail.data))
