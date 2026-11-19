from django.test import TestCase

# Create your tests here.
from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.test import APITestCase

from .models import Notification

User = get_user_model()


class NotificationAPITestCase(APITestCase):
    def setUp(self):
        # 1. 테스트용 사용자 2명 생성 (본인, 타인)
        self.user = User.objects.create_user(
            email='user@university.ac.kr',
            nickname='익명학우1',
            password='password123!',
        )
        self.other_user = User.objects.create_user(
            email='other@university.ac.kr',
            nickname='익명학우2',
            password='password123!',
        )

        # 2. 본인 알림 2개 생성 (1개 읽음, 1개 안 읽음)
        self.notif_read = Notification.objects.create(
            user=self.user,
            type=Notification.Type.CHAT_STARTED,
            target_type=Notification.TargetType.CHAT_ROOM,
            target_id=5,
            title='소유권 확인이 완료되었습니다.',
            message='채팅방에서 물품 반환 일정을 약속해보세요.',
            is_read=True,
        )
        self.notif_unread = Notification.objects.create(
            user=self.user,
            type=Notification.Type.MATCH_CANDIDATE,
            target_type=Notification.TargetType.CANDIDATE,
            target_id=12,
            title='새로운 매칭 후보가 발견되었어요!',
            message="등록하신 '검정색 지갑'과 유사한 습득물이 등록되었습니다.",
            is_read=False,
        )

        # 3. 타인 알림 1개 생성 (타인 접근 차단 및 목록 격리 테스트용)
        self.other_notif = Notification.objects.create(
            user=self.other_user,
            type=Notification.Type.OWNERSHIP_RESULT,
            target_type=Notification.TargetType.CANDIDATE,
            target_id=99,
            title='소유권 확인 실패 안내',
            message='입력하신 정보가 일치하지 않습니다.',
            is_read=False,
        )

    def test_notification_list_success_and_unauthorized(self):
        """1. 알림 목록 조회 테스트 (GET /notifications, /notifications/)"""
        # (실패) 미인증 사용자 요청 -> 401
        res_unauth = self.client.get('/notifications')
        self.assertEqual(res_unauth.status_code, status.HTTP_401_UNAUTHORIZED)

        # (성공) 인증 사용자 요청 -> 본인 알림 2건만 최신순 반환, unread_count = 1
        self.client.force_authenticate(user=self.user)
        res = self.client.get('/notifications')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data['unread_count'], 1)
        self.assertEqual(len(res.data['notifications']), 2)

        # 최신순(-created_at) 정렬 및 명세서 JSON 필드 검증
        first_item = res.data['notifications'][0]
        self.assertEqual(first_item['id'], self.notif_unread.id)
        self.assertEqual(first_item['type'], 'MATCH_CANDIDATE')
        self.assertEqual(first_item['target_id'], 12)
        self.assertFalse(first_item['is_read'])
        self.assertIn('created_at', first_item)
        self.assertNotIn('target_type', first_item)

        # (성공) 끝 슬래시(/notifications/) 경로도 동일하게 200 OK 동작
        res_slash = self.client.get('/notifications/')
        self.assertEqual(res_slash.status_code, status.HTTP_200_OK)
        self.assertEqual(res_slash.data['unread_count'], 1)

    def test_notification_read_success_and_idempotent(self):
        """2. 알림 읽음 처리 정상 동작 및 중복 요청 테스트 (PATCH /notifications/<id>/read)"""
        self.client.force_authenticate(user=self.user)

        # (성공) 안 읽은 알림 읽음 처리 -> 200 OK, is_read: True 반환
        res = self.client.patch(f'/notifications/{self.notif_unread.id}/read')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data, {'id': self.notif_unread.id, 'is_read': True})

        # DB 상태 및 목록 조회 시 unread_count가 0으로 감소했는지 확인
        self.notif_unread.refresh_from_db()
        self.assertTrue(self.notif_unread.is_read)

        res_list = self.client.get('/notifications')
        self.assertEqual(res_list.data['unread_count'], 0)

        # (성공) 이미 읽은 알림 재요청 및 끝 슬래시(/read/) 경로 테스트 -> 200 OK
        res_again = self.client.patch(f'/notifications/{self.notif_unread.id}/read/')
        self.assertEqual(res_again.status_code, status.HTTP_200_OK)
        self.assertEqual(res_again.data['is_read'], True)

    def test_notification_read_error_cases(self):
        """3. 알림 읽음 처리 예외 케이스 테스트 (401, 403, 404)"""
        # (실패) 미인증 사용자 요청 -> 401
        res_unauth = self.client.patch(f'/notifications/{self.notif_unread.id}/read')
        self.assertEqual(res_unauth.status_code, status.HTTP_401_UNAUTHORIZED)

        self.client.force_authenticate(user=self.user)

        # (실패) 존재하지 않는 알림 ID 요청 -> 404
        res_not_found = self.client.patch('/notifications/999999/read')
        self.assertEqual(res_not_found.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(res_not_found.data['detail'], '해당 알림을 찾을 수 없습니다.')

        # (실패) 타인의 알림 읽음 처리 시도 -> 403
        res_forbidden = self.client.patch(f'/notifications/{self.other_notif.id}/read')
        self.assertEqual(res_forbidden.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(res_forbidden.data['detail'], '해당 알림에 대한 접근 권한이 없습니다.')

        # 타인 알림의 DB 상태가 변하지 않았는지 확인
        self.other_notif.refresh_from_db()
        self.assertFalse(self.other_notif.is_read)