from django.test import TestCase
from django.core import mail
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from accounts.models import User, EmailVerification
from items.models import LostItem, FoundItem, MatchCandidate
from chats.models import ChatRoom


class AuthAPITestCase(APITestCase):
    def setUp(self):
        self.send_url = '/auth/email/send'
        self.verify_url = '/auth/email/verify'
        self.logout_url = '/auth/logout'
        self.valid_email = 'student@university.ac.kr'

    def test_full_auth_flow(self):
        # 1. 허용되지 않는 도메인 실패 테스트
        res_invalid = self.client.post(self.send_url, {'email': 'user@gmail.com'}, format='json')
        self.assertEqual(res_invalid.status_code, status.HTTP_400_BAD_REQUEST)

        # 2. 학교 이메일 인증번호 발송 성공
        res_send = self.client.post(self.send_url, {'email': self.valid_email}, format='json')
        self.assertEqual(res_send.status_code, status.HTTP_200_OK)
        self.assertEqual(len(mail.outbox), 1)

        # DB에 저장된 최신 인증번호 조회
        verification = EmailVerification.objects.filter(email=self.valid_email).latest('created_at')

        # 3. 틀린 인증번호 입력 시 400 에러 확인
        res_wrong = self.client.post(
            self.verify_url, {'email': self.valid_email, 'code': '000000'}, format='json'
        )
        self.assertEqual(res_wrong.status_code, status.HTTP_400_BAD_REQUEST)

        # 4. 올바른 인증번호로 최초 로그인 (자동 회원가입)
        res_verify = self.client.post(
            self.verify_url, {'email': self.valid_email, 'code': verification.code}, format='json'
        )
        self.assertEqual(res_verify.status_code, status.HTTP_200_OK)
        self.assertTrue(res_verify.data['is_new_user'])
        self.assertTrue(User.objects.filter(email=self.valid_email).exists())

        access_token = res_verify.data['access_token']
        refresh_token = res_verify.data['refresh_token']

        # 5. 로그아웃 및 토큰 만료 확인
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {access_token}')
        res_logout = self.client.post(
            self.logout_url, {'refresh_token': refresh_token}, format='json'
        )
        self.assertEqual(res_logout.status_code, status.HTTP_200_OK)

        # 이미 로그아웃된 토큰으로 재요청 시 400 에러 확인
        res_logout_again = self.client.post(
            self.logout_url, {'refresh_token': refresh_token}, format='json'
        )
        self.assertEqual(res_logout_again.status_code, status.HTTP_400_BAD_REQUEST)


class MyPageAPITestCase(APITestCase):
    def setUp(self):
        # 1. 테스트용 사용자 생성 (본인 & 타인)
        self.user = User.objects.create_user(
            email='student@university.ac.kr',
            nickname='익명학우1',
            university_name='한국대학교',
            is_verified=True
        )
        self.other_user = User.objects.create_user(
            email='other@university.ac.kr',
            nickname='타인학우',
            university_name='한국대학교',
            is_verified=True
        )

        # 2. 분실물(LostItem) 생성 (실제 모델 필드: owner, item_name, status)[cite: 2, 3]
        self.lost_item_candidate = LostItem.objects.create(
            owner=self.user,
            item_name='검정색 가죽 지갑'
        )
        self.lost_item_waiting = LostItem.objects.create(
            owner=self.user,
            item_name='흰색 무선 이어폰'
        )
        self.other_lost_item = LostItem.objects.create(
            owner=self.other_user,
            item_name='타인의 우산'
        )

        # 3. 습득물(FoundItem) 생성 (필수 필드: found_location, found_at, original_image_url 포함)[cite: 2, 3]
        self.found_item_match = FoundItem.objects.create(
            finder=self.other_user,
            category='지갑',
            item_name='검정색 가죽 지갑',
            found_location='학생회관 1층',
            found_at=timezone.now(),
            original_image_url='https://s3.example.com/found/21_orig.jpg',
            blurred_image_url='https://s3.example.com/found/21_blurred.jpg'
        )
        self.found_item_completed = FoundItem.objects.create(
            finder=self.other_user,
            category='전자기기',
            item_name='검정색 무선 이어폰 케이스',
            found_location='중앙도서관 2층',
            found_at=timezone.now(),
            original_image_url='https://s3.example.com/found/15_orig.jpg',
            blurred_image_url='https://s3.example.com/found/15_blurred.jpg',
            status='COMPLETED'
        )
        self.lost_item_completed = LostItem.objects.create(
            owner=self.user,
            item_name='검정색 무선 이어폰 케이스',
            status='COMPLETED'
        )

        # 4. 매칭 후보 및 활성 채팅방 연결 (lost_item_candidate -> CHATTING 상태)
        self.candidate = MatchCandidate.objects.create(
            lost_item=self.lost_item_candidate,
            found_item=self.found_item_match
        )
        self.active_chat = ChatRoom.objects.create(
            candidate=self.candidate,
            owner=self.user,
            finder=self.other_user,
            status='ACTIVE'
        )

        # 5. 반환 완료 채팅방 생성 (history 조회용)
        self.completed_candidate = MatchCandidate.objects.create(
            lost_item=self.lost_item_completed,
            found_item=self.found_item_completed
        )
        self.completed_chat = ChatRoom.objects.create(
            candidate=self.completed_candidate,
            owner=self.user,
            finder=self.other_user,
            status='COMPLETED',
            completed_at=timezone.now()
        )

        # 엔드포인트 URL
        self.profile_url = '/users/me'
        self.items_url = '/users/me/items'
        self.history_url = '/users/me/history'

    def test_my_profile_and_unauthorized(self):
        # 1. 토큰 없이 요청 시 401 반환
        res_unauth = self.client.get(self.profile_url)
        self.assertEqual(res_unauth.status_code, status.HTTP_401_UNAUTHORIZED)

        # 2. 인증된 사용자 조회 성공 (200 OK)
        self.client.force_authenticate(user=self.user)
        res = self.client.get(self.profile_url)
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data['email'], 'student@university.ac.kr')
        self.assertEqual(res.data['nickname'], '익명학우1')
        self.assertTrue(res.data['is_university_verified'])
        self.assertEqual(res.data['university_name'], '한국대학교')

    def test_my_items_list_and_validation(self):
        self.client.force_authenticate(user=self.user)

        # 1. 잘못된 type 파라미터 400 검증
        res_bad = self.client.get(f'{self.items_url}?type=invalid')
        self.assertEqual(res_bad.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('type', res_bad.data)

        # 2. 분실물(lost) 목록 조회 성공 (본인 글 3건: 진행중 2 + 완료 1)
        res_lost = self.client.get(f'{self.items_url}?type=lost')
        self.assertEqual(res_lost.status_code, status.HTTP_200_OK)
        self.assertEqual(res_lost.data['type'], 'lost')
        self.assertEqual(res_lost.data['total_count'], 3)

        # 3. 습득물(found) 목록 조회 (본인이 등록한 습득물은 0건)
        res_found = self.client.get(f'{self.items_url}?type=found')
        self.assertEqual(res_found.status_code, status.HTTP_200_OK)
        self.assertEqual(res_found.data['total_count'], 0)

    def test_my_item_status_and_permissions(self):
        self.client.force_authenticate(user=self.user)

        # 1. 존재하지 않는 ID 조회 -> 404 Not Found
        res_404 = self.client.get('/users/me/items/99999/status?type=lost')
        self.assertEqual(res_404.status_code, status.HTTP_404_NOT_FOUND)

        # 2. 타인이 등록한 물건 조회 -> 403 Forbidden
        res_403 = self.client.get(f'/users/me/items/{self.other_lost_item.id}/status?type=lost')
        self.assertEqual(res_403.status_code, status.HTTP_403_FORBIDDEN)

        # 3. 채팅 진행 중인 본인 등록 건 조회 -> 200 OK & GO_TO_CHAT 액션 확인
        res_chatting = self.client.get(
            f'/users/me/items/{self.lost_item_candidate.id}/status?type=lost'
        )
        self.assertEqual(res_chatting.status_code, status.HTTP_200_OK)
        self.assertEqual(res_chatting.data['status'], 'CHATTING')
        self.assertEqual(res_chatting.data['ownership_verification']['result'], 'MATCHED')
        self.assertEqual(res_chatting.data['next_action']['action_type'], 'GO_TO_CHAT')
        self.assertEqual(res_chatting.data['next_action']['target_id'], self.active_chat.id)

        # 4. 매칭 대기 중인 본인 등록 건 조회 -> 200 OK & WAITING 상태 확인
        res_waiting = self.client.get(
            f'/users/me/items/{self.lost_item_waiting.id}/status?type=lost'
        )
        self.assertEqual(res_waiting.status_code, status.HTTP_200_OK)
        self.assertEqual(res_waiting.data['status'], 'WAITING')
        self.assertIsNone(res_waiting.data['ownership_verification'])
        self.assertEqual(res_waiting.data['next_action']['action_type'], 'NONE')

    def test_my_history_list(self):
        self.client.force_authenticate(user=self.user)

        res = self.client.get(self.history_url)
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data['total_count'], 1)

        history_item = res.data['history'][0]
        self.assertEqual(history_item['chat_room_id'], self.completed_chat.id)
        self.assertEqual(history_item['role'], 'OWNER')
        self.assertEqual(history_item['item_name'], '검정색 무선 이어폰 케이스')
        self.assertEqual(history_item['status'], 'COMPLETED')