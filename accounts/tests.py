from django.test import TestCase

# Create your tests here.
from django.core import mail
from rest_framework import status
from rest_framework.test import APITestCase
from accounts.models import User, EmailVerification


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