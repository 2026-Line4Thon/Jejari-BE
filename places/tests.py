from django.test import TestCase

# Create your tests here.
from rest_framework import status
from rest_framework.test import APITestCase
from places.models import Place


class PlaceAPITestCase(APITestCase):
    def setUp(self):
        self.places_url = '/places'

    def test_seed_places_and_get_place_list(self):
        # 1. Data Migration(0002_seed_places)으로 13개 건물 데이터가 정상 적재되었는지 검증
        self.assertEqual(Place.objects.count(), 13)
        self.assertTrue(Place.objects.filter(name='중앙도서관').exists())
        self.assertTrue(Place.objects.filter(name='학생회관').exists())
        self.assertTrue(Place.objects.filter(name='공학관').exists())

        # 2. 비로그인 상태로 GET /places 호출 성공 (200 OK)
        res = self.client.get(self.places_url)
        self.assertEqual(res.status_code, status.HTTP_200_OK)

        # 3. 응답 데이터 구조 및 필드 검증
        self.assertIn('places', res.data)
        places = res.data['places']
        self.assertEqual(len(places), 13)

        first_place = places[0]
        self.assertIn('id', first_place)
        self.assertIn('name', first_place)
        self.assertIn('latitude', first_place)
        self.assertIn('longitude', first_place)

        # 4. Meta ordering = ['name'] 가나다순 정렬 검증 ('경영관'이 첫 번째)
        self.assertEqual(first_place['name'], '경영관')