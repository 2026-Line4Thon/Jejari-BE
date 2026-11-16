from django.test import TestCase

# Create your tests here.
from datetime import timedelta
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase
from rest_framework_simplejwt.tokens import RefreshToken

from accounts.models import User
from items.models import FoundItem, LostItem, MatchCandidate, Notification


class ItemsAPITestCase(APITestCase):
    def setUp(self):
        # 1. 테스트용 유저 2명 생성 (본인 & 타인)
        self.user = User.objects.create_user(
            email='owner@university.ac.kr',
            nickname='분실자학우1'
        )
        self.other_user = User.objects.create_user(
            email='finder@university.ac.kr',
            nickname='습득자학우2'
        )

        # JWT 토큰 발급 및 인증 헤더 세팅 헬퍼
        refresh = RefreshToken.for_user(self.user)
        self.access_token = str(refresh.access_token)
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {self.access_token}')

        # 2. 습득물 데이터 생성 (총 12개: 페이지네이션 테스트용 + 반환완료 1개)
        now = timezone.now()
        self.found_items = []
        for i in range(1, 13):
            item = FoundItem.objects.create(
                finder=self.other_user,
                category='전자기기',
                item_name=f'테스트 습득물 {i}',
                color='검정색',
                brand='Apple',
                found_location=f'공학관 {i}층 로비',
                found_at=now - timedelta(hours=i),
                storage_status='직접 보관 중',
                original_image_url=f'https://s3.example.com/found/{i}_orig.jpg',
                blurred_image_url=f'https://s3.example.com/found/{i}_blurred.jpg',
                private_features=f'비밀 특징 {i}번 (절대 노출되면 안 됨)',
                status='REGISTERED'
            )
            self.found_items.append(item)

        # 반환 완료된 습득물 1개 추가 (홈/목록에서 제외되어야 함)
        self.completed_item = FoundItem.objects.create(
            finder=self.other_user,
            category='지갑/카드',
            item_name='반환완료된 지갑',
            found_location='학생회관 1층',
            found_at=now - timedelta(days=1),
            original_image_url='https://s3.example.com/found/done_orig.jpg',
            blurred_image_url='https://s3.example.com/found/done_blurred.jpg',
            private_features='비밀번호 1234',
            status='COMPLETED'
        )

        # 3. 분실물 및 매칭 후보 생성 (진행 중 2건, 제외됨 1건 -> my_matching_count == 2 여야 함)
        self.lost_item = LostItem.objects.create(
            owner=self.user,
            item_name='검정색 무선 이어폰 케이스',
            status='CANDIDATE_FOUND'
        )
        MatchCandidate.objects.create(
            lost_item=self.lost_item,
            found_item=self.found_items[0],
            status='PENDING'
        )
        MatchCandidate.objects.create(
            lost_item=self.lost_item,
            found_item=self.found_items[1],
            status='VERIFIED'
        )
        MatchCandidate.objects.create(
            lost_item=self.lost_item,
            found_item=self.found_items[2],
            status='REJECTED'  # 제외된 후보는 카운트에서 빠져야 함
        )

        # 4. 알림 생성 (본인 알림 2개: 안읽음 1, 읽음 1 / 타인 알림 1개)
        self.my_unread_noti = Notification.objects.create(
            user=self.user,
            type='MATCH_CANDIDATE',
            title='새로운 매칭 후보가 발견되었어요!',
            message='유사한 습득물이 등록되었습니다.',
            target_id=1,
            is_read=False
        )
        self.my_read_noti = Notification.objects.create(
            user=self.user,
            type='CHAT_STARTED',
            title='채팅이 시작되었습니다.',
            message='습득자와 채팅을 진행해 주세요.',
            target_id=10,
            is_read=True
        )
        self.other_user_noti = Notification.objects.create(
            user=self.other_user,
            type='MATCH_CANDIDATE',
            title='타인의 알림',
            message='타인에게만 보여야 하는 알림입니다.',
            target_id=2,
            is_read=False
        )

    # ---------------------------------------------------------
    # 1. 메인 홈 정보 조회 (GET /home)
    # ---------------------------------------------------------
    def test_home_view_success_and_unauthorized(self):
        # 토큰 없이 요청 시 401
        self.client.credentials()
        res_unauth = self.client.get('/home')
        self.assertEqual(res_unauth.status_code, status.HTTP_401_UNAUTHORIZED)

        # 정상 요청 시 200
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {self.access_token}')
        res = self.client.get('/home')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data['my_matching_count'], 2)
        self.assertEqual(len(res.data['recent_found_items']), 10)  # 최대 10개 노출

        # 민감 필드(private_features, original_image_url)가 응답에 포함되지 않는지 검증
        first_item = res.data['recent_found_items'][0]
        self.assertIn('blurred_image_url', first_item)
        self.assertNotIn('private_features', first_item)
        self.assertNotIn('original_image_url', first_item)

    # ---------------------------------------------------------
    # 2. 습득물 전체 목록 조회 (GET /items/found)
    # ---------------------------------------------------------
    def test_found_item_list_pagination_and_validation(self):
        # 1페이지 (size=10) 조회 -> 전체 12건 중 10건 반환, has_next=True
        res_p1 = self.client.get('/items/found?page=1&size=10')
        self.assertEqual(res_p1.status_code, status.HTTP_200_OK)
        self.assertEqual(res_p1.data['total_count'], 12)
        self.assertTrue(res_p1.data['has_next'])
        self.assertEqual(len(res_p1.data['items']), 10)

        # 2페이지 (size=10) 조회 -> 나머지 2건 반환, has_next=False
        res_p2 = self.client.get('/items/found?page=2&size=10')
        self.assertEqual(res_p2.status_code, status.HTTP_200_OK)
        self.assertFalse(res_p2.data['has_next'])
        self.assertEqual(len(res_p2.data['items']), 2)

        # 잘못된 page 파라미터 입력 시 400 Bad Request
        res_bad = self.client.get('/items/found?page=abc&size=10')
        self.assertEqual(res_bad.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('page', res_bad.data)

    # ---------------------------------------------------------
    # 3. 습득물 상세 조회 (GET /items/found/<int:item_id>)
    # ---------------------------------------------------------
    def test_found_item_detail(self):
        target = self.found_items[0]
        res = self.client.get(f'/items/found/{target.id}')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data['id'], target.id)
        self.assertEqual(res.data['category'], '전자기기')
        self.assertEqual(res.data['brand'], 'Apple')
        # 비공개 특징이 상세 조회에서도 차단되는지 확인
        self.assertNotIn('private_features', res.data)
        self.assertNotIn('original_image_url', res.data)

        # 존재하지 않는 습득물 ID 조회 시 404 Not Found
        res_404 = self.client.get('/items/found/999999')
        self.assertEqual(res_404.status_code, status.HTTP_404_NOT_FOUND)

    # ---------------------------------------------------------
    # 4. 알림 목록 조회 & 읽음 처리 (GET /notifications, PATCH /notifications/<id>/read)
    # ---------------------------------------------------------
    def test_notifications_list_and_read(self):
        # 내 알림 목록 조회 (타인 알림은 제외되고 본인 알림 2개만 조회, unread_count == 1)
        res_list = self.client.get('/notifications')
        self.assertEqual(res_list.status_code, status.HTTP_200_OK)
        self.assertEqual(res_list.data['unread_count'], 1)
        self.assertEqual(len(res_list.data['notifications']), 2)

        # 내 안읽은 알림 읽음 처리 성공 -> 200 OK & is_read == True
        res_read = self.client.patch(f'/notifications/{self.my_unread_noti.id}/read')
        self.assertEqual(res_read.status_code, status.HTTP_200_OK)
        self.assertTrue(res_read.data['is_read'])

        # 읽음 처리 후 다시 목록 조회 시 unread_count == 0
        res_list_after = self.client.get('/notifications')
        self.assertEqual(res_list_after.data['unread_count'], 0)

        # 타인의 알림 읽음 처리 시도 -> 403 Forbidden
        res_forbidden = self.client.patch(f'/notifications/{self.other_user_noti.id}/read')
        self.assertEqual(res_forbidden.status_code, status.HTTP_403_FORBIDDEN)

        # 존재하지 않는 알림 읽음 처리 시도 -> 404 Not Found
        res_not_found = self.client.patch('/notifications/999999/read')
        self.assertEqual(res_not_found.status_code, status.HTTP_404_NOT_FOUND)