import random
from datetime import timedelta
from django.utils import timezone
from django.core.mail import send_mail
from django.conf import settings
from django.db.models import Q
from rest_framework import status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.exceptions import TokenError
from drf_spectacular.utils import extend_schema, OpenApiParameter, OpenApiTypes

from .models import User, EmailVerification
from items.models import LostItem, FoundItem
from matching.models import MatchCandidate, OwnershipCheck
from chats.models import ChatRoom
from .serializers import (
    EmailSendSerializer,
    EmailVerifySerializer,
    LogoutSerializer,
    MyProfileSerializer,
    MyItemSerializer,
    MyHistorySerializer,
)

TEST_JUDGE_EMAIL = "judge@university.ac.kr" 
TEST_JUDGE_CODE = "123456"          

class EmailSendView(APIView):
    """
    POST /auth/email/send
    학교 계정 인증번호 발송
    """
    permission_classes = [AllowAny]

    @extend_schema(
        summary="학교 계정 인증번호 발송",
        request=EmailSendSerializer,
        responses={200: OpenApiTypes.OBJECT},
        tags=["A. 로그인 및 공통"],
    )
    def post(self, request):
        serializer = EmailSendSerializer(data=request.data)
        if not serializer.is_valid():
            if 'email' in serializer.errors:
                first_error = str(serializer.errors['email'][0])
                if "유효한 학교 이메일" in first_error:
                    return Response({"detail": first_error}, status=status.HTTP_400_BAD_REQUEST)
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        email = serializer.validated_data['email'].lower()
        now = timezone.now()

        # 심사위원단 테스트 계정은 발송 횟수 제한(429) 및 실제 메일 발송 생략
        if email == TEST_JUDGE_EMAIL:
            return Response(
                {
                    "message": "인증번호가 발송되었습니다.",
                    "expires_in": 300,
                    "dev_code": TEST_JUDGE_CODE,
                },
                status=status.HTTP_200_OK
            )

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
                "expires_in": 300,
                # 프론트엔드 Swagger 테스트 편의용 (실제 메일 서버 연동 후 제거)
                "dev_code": verification_code,
            },
            status=status.HTTP_200_OK
        )


class EmailVerifyView(APIView):
    """
    POST /auth/email/verify
    인증번호 확인 및 로그인 (최초 인증 시 자동 계정 생성)
    """
    permission_classes = [AllowAny]

    @extend_schema(
        summary="인증번호 확인 및 로그인",
        request=EmailVerifySerializer,
        responses={200: OpenApiTypes.OBJECT},
        tags=["A. 로그인 및 공통"],
    )
    def post(self, request):
        serializer = EmailVerifySerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        email = serializer.validated_data['email'].lower()
        code = serializer.validated_data['code']

        # 심사위원단 테스트 계정일 경우 마스터 번호만 확인하고 DB 검증 우회
        if email == TEST_JUDGE_EMAIL:
            if code != TEST_JUDGE_CODE:
                return Response(
                    {"detail": "인증번호가 일치하지 않습니다."},
                    status=status.HTTP_400_BAD_REQUEST
                )
        else:
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

    @extend_schema(
        summary="로그아웃",
        request=LogoutSerializer,
        responses={200: OpenApiTypes.OBJECT},
        tags=["A. 로그인 및 공통"],
    )
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


class MyProfileView(APIView):
    """
    GET /users/me
    내 정보 및 인증 정보 조회
    """
    permission_classes = [IsAuthenticated]

    @extend_schema(
        summary="내 정보 및 인증 정보 조회",
        responses={200: MyProfileSerializer},
        tags=["H. 마이페이지"],
    )
    def get(self, request):
        serializer = MyProfileSerializer(request.user)
        return Response(serializer.data, status=status.HTTP_200_OK)


class MyItemListView(APIView):
    """
    GET /users/me/items?type=lost|found
    내 등록 내역 목록 조회
    """
    permission_classes = [IsAuthenticated]

    @extend_schema(
        summary="내 등록 내역 목록 조회",
        parameters=[
            OpenApiParameter(
                name='type',
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                required=True,
                enum=['lost', 'found'],
                description="조회할 물품 유형 ('lost' 또는 'found')",
            ),
        ],
        responses={200: MyItemSerializer(many=True)},
        tags=["H. 마이페이지"],
    )
    def get(self, request):
        item_type = request.query_params.get('type')
        if item_type not in ('lost', 'found'):
            return Response(
                {"type": ["유효한 선택지가 아닙니다. ('lost' 또는 'found'만 가능)"]},
                status=status.HTTP_400_BAD_REQUEST
            )

        serialized_items = []

        if item_type == 'lost':
            queryset = LostItem.objects.filter(user=request.user).select_related('image').order_by('-created_at')
            for item in queryset:
                status_code, status_label = self._resolve_lost_status(item)
                serialized_items.append({
                    "id": item.id,
                    "item_type": "LOST",
                    "item_name": item.item_name,
                    "thumbnail_url": item.image.image_url if item.image else None,
                    "status": status_code,
                    "status_label": status_label,
                    "created_at": item.created_at,
                })
        else:
            queryset = FoundItem.objects.filter(finder=request.user).select_related('image').order_by('-created_at')
            for item in queryset:
                status_code, status_label = self._resolve_found_status(item)
                serialized_items.append({
                    "id": item.id,
                    "item_type": "FOUND",
                    "item_name": item.item_name,
                    "thumbnail_url": item.image.image_url if item.image else None,
                    "status": status_code,
                    "status_label": status_label,
                    "created_at": item.created_at,
                })

        serializer = MyItemSerializer(serialized_items, many=True)
        return Response(
            {
                "type": item_type,
                "total_count": len(serialized_items),
                "items": serializer.data,
            },
            status=status.HTTP_200_OK
        )

    def _resolve_lost_status(self, item):
        if item.status == 'COMPLETED':
            return 'COMPLETED', '반환 완료'
        active_chat = ChatRoom.objects.filter(candidate__lost_item=item, status='ACTIVE').first()
        if active_chat:
            return 'CHATTING', '채팅 진행 중'
        has_candidates = item.candidates.filter(status__in=MatchCandidate.ACTIVE_STATUSES).exists()
        if has_candidates:
            return 'CANDIDATE_FOUND', '매칭 후보 있음'
        return 'WAITING', '매칭 대기 중'

    def _resolve_found_status(self, item):
        if item.status == 'COMPLETED':
            return 'COMPLETED', '반환 완료'
        active_chat = ChatRoom.objects.filter(candidate__found_item=item, status='ACTIVE').first()
        if active_chat:
            return 'CHATTING', '채팅 진행 중'
        has_candidates = item.candidates.filter(status__in=MatchCandidate.ACTIVE_STATUSES).exists()
        if has_candidates:
            return 'CANDIDATE_FOUND', '매칭 후보 있음'
        return 'WAITING', '매칭 대기 중'


class MyItemStatusView(APIView):
    """
    GET /users/me/items/<int:item_id>/status?type=lost|found
    내 등록 건 진행 상태 조회
    """
    permission_classes = [IsAuthenticated]

    @extend_schema(
        summary="내 등록 건 진행 상태 조회",
        parameters=[
            OpenApiParameter(
                name='type',
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                required=True,
                enum=['lost', 'found'],
                description="조회할 물품 유형 ('lost' 또는 'found')",
            ),
        ],
        responses={200: OpenApiTypes.OBJECT},
        tags=["H. 마이페이지"],
    )
    def get(self, request, item_id):
        item_type = request.query_params.get('type')
        if item_type not in ('lost', 'found'):
            return Response(
                {"type": ["유효한 선택지가 아닙니다. ('lost' 또는 'found'만 가능)"]},
                status=status.HTTP_400_BAD_REQUEST
            )

        if item_type == 'lost':
            item = LostItem.objects.filter(id=item_id).first()
            if not item:
                return Response(
                    {"detail": "해당 등록 내역을 찾을 수 없습니다."},
                    status=status.HTTP_404_NOT_FOUND
                )
            if item.user != request.user:
                return Response(
                    {"detail": "해당 등록 내역에 대한 조회 권한이 없습니다."},
                    status=status.HTTP_403_FORBIDDEN
                )
        else:
            item = FoundItem.objects.filter(id=item_id).first()
            if not item:
                return Response(
                    {"detail": "해당 등록 내역을 찾을 수 없습니다."},
                    status=status.HTTP_404_NOT_FOUND
                )
            if item.finder != request.user:
                return Response(
                    {"detail": "해당 등록 내역에 대한 조회 권한이 없습니다."},
                    status=status.HTTP_403_FORBIDDEN
                )

        # 상태 및 다음 액션 계산
        status_code, status_label, verification_data, next_action = self._build_progress_payload(
            item, item_type
        )

        return Response(
            {
                "item_id": item.id,
                "item_type": item_type.upper(),
                "item_name": item.item_name,
                "status": status_code,
                "status_label": status_label,
                "ownership_verification": verification_data,
                "next_action": next_action,
            },
            status=status.HTTP_200_OK
        )

    def _build_progress_payload(self, item, item_type):
        chat_filter = (
            {'candidate__lost_item': item}
            if item_type == 'lost'
            else {'candidate__found_item': item}
        )
        chat_room = ChatRoom.objects.filter(**chat_filter).order_by('-created_at').first()

        if chat_room:
            is_completed = (chat_room.status == 'COMPLETED')
            return (
                'COMPLETED' if is_completed else 'CHATTING',
                '반환 완료' if is_completed else '채팅 진행 중',
                {"result": "MATCHED", "result_label": "소유권 일치"},
                {
                    "action_type": "GO_TO_CHAT",
                    "target_id": chat_room.id,
                    "button_label": "채팅방으로 이동"
                }
            )

        candidate = item.candidates.filter(
            status__in=MatchCandidate.ACTIVE_STATUSES
        ).order_by('-created_at').first()
        if candidate:
            check_obj = candidate.ownership_checks.order_by('-created_at').first()

            if check_obj:
                if check_obj.result == OwnershipCheck.Result.MATCHED:
                    return (
                        'VERIFIED',
                        '소유권 일치',
                        {"result": "MATCHED", "result_label": "소유권 일치"},
                        {
                            "action_type": "VIEW_VERIFICATION",
                            "target_id": check_obj.id,
                            "button_label": "소유권 확인 결과 보기"
                        }
                    )
                elif check_obj.result == OwnershipCheck.Result.NEED_MORE:
                    return (
                        'VERIFYING',
                        '추가 확인 필요',
                        {"result": "ADDITIONAL_NEEDED", "result_label": "추가 확인 필요"},
                        {
                            "action_type": "VIEW_VERIFICATION",
                            "target_id": check_obj.id,
                            "button_label": "추가 질문 답변하기"
                        }
                    )

            return (
                'CANDIDATE_FOUND',
                '매칭 후보 있음',
                None,
                {
                    "action_type": "VIEW_CANDIDATES" if item_type == 'lost' else "NONE",
                    "target_id": item.id if item_type == 'lost' else None,
                    "button_label": "매칭 후보 확인하기" if item_type == 'lost' else "분실자 확인 대기 중"
                }
            )

        return (
            'WAITING',
            '매칭 대기 중',
            None,
            {
                "action_type": "NONE",
                "target_id": None,
                "button_label": "매칭 대기 중"
            }
        )


class MyHistoryView(APIView):
    """
    GET /users/me/history
    내 반환 완료 내역 조회
    """
    permission_classes = [IsAuthenticated]

    @extend_schema(
        summary="내 반환 완료 내역 조회",
        responses={200: MyHistorySerializer(many=True)},
        tags=["H. 마이페이지"],
    )
    def get(self, request):
        completed_rooms = ChatRoom.objects.filter(
            Q(owner=request.user) | Q(finder=request.user),
            status='COMPLETED'
        ).select_related('candidate__found_item__image').order_by('-completed_at')

        history_list = []
        for room in completed_rooms:
            is_owner = (room.owner == request.user)
            target_item = room.candidate.found_item

            history_list.append({
                "chat_room_id": room.id,
                "role": "OWNER" if is_owner else "FINDER",
                "item_id": target_item.id,
                "item_name": target_item.item_name,
                "blurred_image_url": target_item.image.image_url if target_item.image else None,
                "status": "COMPLETED",
                "completed_at": room.completed_at,
            })

        serializer = MyHistorySerializer(history_list, many=True)
        return Response(
            {
                "total_count": len(history_list),
                "history": serializer.data,
            },
            status=status.HTTP_200_OK
        )