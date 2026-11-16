import random
from datetime import timedelta
from django.utils import timezone
from django.core.mail import send_mail
from django.conf import settings
from rest_framework import status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.exceptions import TokenError

from .models import User, EmailVerification
from .serializers import EmailSendSerializer, EmailVerifySerializer, LogoutSerializer


class EmailSendView(APIView):
    """
    POST /auth/email/send
    학교 계정 인증번호 발송
    """
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = EmailSendSerializer(data=request.data)
        if not serializer.is_valid():
            if 'email' in serializer.errors:
                first_error = str(serializer.errors['email'][0])
                if "유효한 학교 이메일" in first_error:
                    return Response({"detail": first_error}, status=status.HTTP_400_BAD_REQUEST)
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        email = serializer.validated_data['email']
        now = timezone.now()

        # 최근 10분 내 발송 횟수 제한 확인 (최대 5회)
        recent_count = EmailVerification.objects.filter(
            email=email,
            created_at__gte=now - timedelta(minutes=10)
        ).count()
        if recent_count >= 5:
            return Response(
                {"detail": "인증번호 발송 횟수를 초과했습니다. 잠시 후 다시 시도해주세요."},
                status=status.HTTP_429_TOO_MANY_REQUESTS
            )

        # 6자리 인증번호 생성 및 DB(EmailVerification) 저장
        verification_code = f"{random.randint(0, 999999):06d}"
        EmailVerification.objects.create(
            email=email,
            code=verification_code,
            expires_at=now + timedelta(seconds=300),
            is_used=False
        )

        # 이메일 발송
        send_mail(
            subject='[캠퍼스 분실물 서비스] 학교 이메일 인증번호 안내',
            message=f'인증번호는 [{verification_code}] 입니다. 5분 이내에 입력해주세요.',
            from_email=getattr(settings, 'DEFAULT_FROM_EMAIL', 'noreply@campus.ac.kr'),
            recipient_list=[email],
            fail_silently=False,
        )

        return Response(
            {
                "message": "인증번호가 발송되었습니다.",
                "expires_in": 300
            },
            status=status.HTTP_200_OK
        )


class EmailVerifyView(APIView):
    """
    POST /auth/email/verify
    인증번호 확인 및 로그인 (최초 인증 시 자동 계정 생성)
    """
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = EmailVerifySerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        email = serializer.validated_data['email'].lower()
        code = serializer.validated_data['code']

        # 가장 최근에 발송된 미사용 인증 내역 조회
        verification = EmailVerification.objects.filter(
            email=email,
            is_used=False
        ).order_by('-created_at').first()

        # 1. 인증 내역이 없거나 만료 시간이 지난 경우
        if not verification or verification.expires_at < timezone.now():
            return Response(
                {"detail": "인증번호가 만료되었습니다. 재발송 후 다시 시도해주세요."},
                status=status.HTTP_400_BAD_REQUEST
            )

        # 2. 인증번호 불일치
        if verification.code != code:
            return Response(
                {"detail": "인증번호가 일치하지 않습니다."},
                status=status.HTTP_400_BAD_REQUEST
            )

        # 인증 성공 처리 (재사용 방지)
        verification.is_used = True
        verification.save(update_fields=['is_used'])

        # 3. 기존 유저 조회 또는 신규 유저 자동 생성
        user, is_new_user = User.objects.get_or_create(
            email=email,
            defaults={
                'nickname': self._generate_unique_nickname(),
                'is_verified': True,
            }
        )

        # 4. JWT 토큰 발급
        refresh = RefreshToken.for_user(user)

        return Response(
            {
                "access_token": str(refresh.access_token),
                "refresh_token": str(refresh),
                "is_new_user": is_new_user,
                "user": {
                    "id": user.id,
                    "email": user.email,
                    "nickname": user.nickname
                }
            },
            status=status.HTTP_200_OK
        )

    def _generate_unique_nickname(self):
        next_num = User.objects.count() + 1
        while True:
            nickname = f"익명학우{next_num}"
            if not User.objects.filter(nickname=nickname).exists():
                return nickname
            next_num += 1


class LogoutView(APIView):
    """
    POST /auth/logout
    로그아웃 (Refresh Token 블랙리스트 처리)
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = LogoutSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        refresh_token = serializer.validated_data['refresh_token']

        try:
            token = RefreshToken(refresh_token)
            token.blacklist()
        except TokenError:
            return Response(
                {"detail": "유효하지 않거나 이미 만료된 토큰입니다."},
                status=status.HTTP_400_BAD_REQUEST
            )

        return Response(
            {"message": "로그아웃되었습니다."},
            status=status.HTTP_200_OK
        )