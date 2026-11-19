from django.conf import settings
from django.core.paginator import Paginator, EmptyPage
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework import status
from rest_framework.exceptions import NotFound, PermissionDenied

from ai.images import InvalidImage
from matching.models import MatchCandidate

from . import feature_chat
from .models import FeatureChat, FoundItem, ItemStatus, LostItem
from .serializers import (
    FoundItemListSerializer,
    FeatureChatAnswerSerializer,
    FeatureChatResponseSerializer,
    FeatureChatStartSerializer,
    FoundItemCreateResponseSerializer,
    FoundItemCreateSerializer,
    FoundItemDetailSerializer,
    ImageAnalyzeRequestSerializer,
    ImageAnalyzeResponseSerializer,
    LostItemCreateResponseSerializer,
    LostItemCreateSerializer,
    LostItemDetailSerializer,
)
from .services import (
    AnalysisUnavailable,
    NoItemDetected,
    create_analyzed_image,
    register_found_item,
    register_lost_item,
)


# 1. 메인 홈 정보 조회 (GET /home)
class HomeView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        my_matching_count = MatchCandidate.objects.filter(
            lost_item__user=request.user,
            status__in=MatchCandidate.ACTIVE_STATUSES,
        ).exclude(lost_item__status=ItemStatus.COMPLETED).count()

        recent_items = (
            FoundItem.objects.select_related('image', 'place')
            .exclude(status=ItemStatus.COMPLETED)[:10]
        )
        serializer = FoundItemListSerializer(recent_items, many=True)

        return Response(
            {
                "my_matching_count": my_matching_count,
                "recent_found_items": serializer.data,
            },
            status=status.HTTP_200_OK
        )


# 2. 습득물 전체 목록 조회 (GET /items/found?page=1&size=10)
class FoundItemListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        page_param = request.query_params.get('page', '1')
        size_param = request.query_params.get('size', '10')

        # page 정수 검증
        try:
            page = int(page_param)
            if page < 1:
                raise ValueError
        except ValueError:
            return Response(
                {"page": ["유효한 정수(integer)를 입력하세요."]},
                status=status.HTTP_400_BAD_REQUEST
            )

        # size 정수 검증
        try:
            size = int(size_param)
            if size < 1:
                raise ValueError
        except ValueError:
            return Response(
                {"size": ["유효한 정수(integer)를 입력하세요."]},
                status=status.HTTP_400_BAD_REQUEST
            )

        queryset = (
            FoundItem.objects.select_related('image', 'place')
            .exclude(status=ItemStatus.COMPLETED)
            .order_by('-created_at')
        )
        paginator = Paginator(queryset, size)
        total_count = paginator.count

        try:
            page_obj = paginator.page(page)
            items = page_obj.object_list
            has_next = page_obj.has_next()
        except EmptyPage:
            items = []
            has_next = False

        serializer = FoundItemListSerializer(items, many=True)

        return Response(
            {
                "total_count": total_count,
                "has_next": has_next,
                "items": serializer.data,
            },
            status=status.HTTP_200_OK
        )


# 3. 습득물 상세 조회 (GET /items/found/<int:item_id>)
class FoundItemDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, item_id):
        try:
            found_item = FoundItem.objects.select_related('image', 'place').get(id=item_id)
        except FoundItem.DoesNotExist:
            return Response(
                {"detail": "해당 습득물 정보를 찾을 수 없습니다."},
                status=status.HTTP_404_NOT_FOUND
            )

        serializer = FoundItemDetailSerializer(found_item)
        return Response(serializer.data, status=status.HTTP_200_OK)



# ---------------------------------------------------------------------------
# 사진 분석 (C-02, D-02, D-03, S-01, S-02, S-04)
# ---------------------------------------------------------------------------

INVALID_IMAGE_MESSAGE = 'jpg, png 형식의 {limit}MB 이하 이미지만 업로드할 수 있습니다.'
TAG_FIELDS = ('category', 'item_name', 'color', 'brand')


class ItemImageAnalyzeView(APIView):
    """
    사진을 올리면 AI가 종류·물건명·색상·브랜드·특징을 추출하고,
    민감정보가 보이면 공개용 사진을 블러 처리해 저장한다.
    반환한 image_id는 분실물·습득물 등록 API에 그대로 넘긴다.
    """

    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]
    timeout_message = '분석 시간이 초과되었습니다. 잠시 후 다시 시도해 주세요.'

    @extend_schema(
        request={'multipart/form-data': ImageAnalyzeRequestSerializer},
        responses={
            201: ImageAnalyzeResponseSerializer,
            400: OpenApiResponse(description='이미지 누락, jpg·png가 아님, 용량 초과'),
            422: OpenApiResponse(description='사진에서 물건을 찾지 못함'),
            504: OpenApiResponse(description='AI 분석 시간 초과·실패'),
        },
    )
    def post(self, request):
        serializer = ImageAnalyzeRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        upload = serializer.validated_data['image']

        limit_mb = settings.IMAGE_MAX_UPLOAD_MB
        invalid = Response(
            {'detail': INVALID_IMAGE_MESSAGE.format(limit=limit_mb)},
            status=status.HTTP_400_BAD_REQUEST,
        )
        if upload.size > limit_mb * 1024 * 1024:
            return invalid

        try:
            item_image, analysis = create_analyzed_image(request.user, upload)
        except InvalidImage:
            return invalid
        except NoItemDetected:
            return Response(
                {'detail': '사진에서 물건을 찾지 못했습니다. 다른 사진을 올려 주세요.'},
                status=status.HTTP_422_UNPROCESSABLE_ENTITY,
            )
        except AnalysisUnavailable:
            return Response({'detail': self.timeout_message}, status=status.HTTP_504_GATEWAY_TIMEOUT)

        tags = {field: getattr(analysis, field) for field in TAG_FIELDS}
        tags['features'] = analysis.features
        data = {
            'image_id': item_image.id,
            'image_url': request.build_absolute_uri(item_image.image_url),
            'is_blurred': item_image.is_blurred,
            'tags': tags,
            'unrecognized_fields': [field for field in TAG_FIELDS if tags[field] is None],
        }
        return Response(ImageAnalyzeResponseSerializer(data).data, status=status.HTTP_201_CREATED)


# ---------------------------------------------------------------------------
# 분실물 등록 (C-05, E-01) · 등록 결과 조회 (C-06)
# ---------------------------------------------------------------------------

class LostItemCreateView(APIView):
    """분실물을 저장하고, 커밋 후 백그라운드에서 자동 매칭을 실행한다."""

    permission_classes = [IsAuthenticated]

    @extend_schema(
        request=LostItemCreateSerializer,
        responses={
            201: LostItemCreateResponseSerializer,
            400: OpenApiResponse(description='필수 값 누락, 사진·설명 모두 없음, 시간 범위 오류'),
            404: OpenApiResponse(description='이미지·장소·특징 구체화 대화를 찾을 수 없음'),
            504: OpenApiResponse(description='설명문 임베딩 생성 실패'),
        },
    )
    def post(self, request):
        serializer = LostItemCreateSerializer(data=request.data, context={'request': request})
        serializer.is_valid(raise_exception=True)

        try:
            lost_item = register_lost_item(request.user, serializer.validated_data)
        except AnalysisUnavailable:
            return Response(
                {'detail': '등록 처리 시간이 초과되었습니다. 잠시 후 다시 시도해 주세요.'},
                status=status.HTTP_504_GATEWAY_TIMEOUT,
            )

        data = {
            'lost_item_id': lost_item.id,
            'status': lost_item.status,
            'message': '분실물이 등록되었습니다. 비슷한 물건을 찾고 있어요.',
        }
        return Response(LostItemCreateResponseSerializer(data).data, status=status.HTTP_201_CREATED)


class LostItemDetailView(APIView):
    """등록한 분실물 정보와 매칭 진행 상태. 등록자 본인만 조회 가능."""

    permission_classes = [IsAuthenticated]

    @extend_schema(responses={200: LostItemDetailSerializer})
    def get(self, request, item_id):
        lost_item = LostItem.objects.select_related('image', 'place').filter(id=item_id).first()
        if lost_item is None:
            raise NotFound('분실물을 찾을 수 없습니다.')
        if lost_item.user_id != request.user.id:
            raise PermissionDenied()
        serializer = LostItemDetailSerializer(lost_item, context={'request': request})
        return Response(serializer.data, status=status.HTTP_200_OK)


# ---------------------------------------------------------------------------
# 습득물 등록 (D-05, E-01)
# GET /items/found(목록)과 URL이 같아서 목록 뷰에 POST를 더한 뷰로 라우팅
# ---------------------------------------------------------------------------

class FoundItemListCreateView(FoundItemListView):
    @extend_schema(
        request=FoundItemCreateSerializer,
        responses={
            201: FoundItemCreateResponseSerializer,
            400: OpenApiResponse(description='필수 값 누락, 인계인데 보관 장소 없음, 미래 습득 시각'),
            404: OpenApiResponse(description='이미지·장소를 찾을 수 없음'),
            504: OpenApiResponse(description='설명문 임베딩 생성 실패'),
        },
    )
    def post(self, request):
        """습득물을 저장하고, 커밋 후 백그라운드에서 자동 매칭을 실행한다."""
        serializer = FoundItemCreateSerializer(data=request.data, context={'request': request})
        serializer.is_valid(raise_exception=True)

        try:
            found_item = register_found_item(request.user, serializer.validated_data)
        except AnalysisUnavailable:
            return Response(
                {'detail': '등록 처리 시간이 초과되었습니다. 잠시 후 다시 시도해 주세요.'},
                status=status.HTTP_504_GATEWAY_TIMEOUT,
            )

        data = {
            'found_item_id': found_item.id,
            'status': found_item.status,
            'message': '습득물이 등록되었습니다. 주인을 찾고 있어요.',
        }
        return Response(FoundItemCreateResponseSerializer(data).data, status=status.HTTP_201_CREATED)


# ---------------------------------------------------------------------------
# AI 특징 구체화 (C-04, S-03)
# ---------------------------------------------------------------------------

def _get_own_chat(request, chat_id):
    chat = FeatureChat.objects.filter(id=chat_id, user=request.user).first()
    if chat is None:
        raise NotFound('대화를 찾을 수 없습니다.')
    return chat


def _chat_finished_response():
    return Response({'detail': '이미 종료된 대화입니다.'}, status=status.HTTP_409_CONFLICT)


def _finished_payload(chat_id, summary, features):
    return {'chat_id': chat_id, 'question': None, 'is_finished': True, 'summary': summary, 'features': features}


class FeatureChatStartView(APIView):
    """사진·설명으로 이미 파악된 항목을 건너뛰고 첫 질문을 만든다."""

    permission_classes = [IsAuthenticated]

    @extend_schema(
        request=FeatureChatStartSerializer,
        responses={
            201: FeatureChatResponseSerializer,
            400: OpenApiResponse(description='사진·설명 모두 없음'),
            404: OpenApiResponse(description='없거나 본인이 올리지 않은 이미지'),
        },
    )
    def post(self, request):
        serializer = FeatureChatStartSerializer(data=request.data, context={'request': request})
        serializer.is_valid(raise_exception=True)
        chat, known, question = feature_chat.start(
            request.user, serializer.validated_data['image'], serializer.validated_data['description']
        )
        if question is None:  # 모든 항목을 이미 알고 있어 바로 종료
            data = _finished_payload(chat.id, chat.summary, feature_chat.features_of(chat))
            data['known'] = known
        else:
            data = {'chat_id': chat.id, 'known': known, 'question': question, 'is_finished': False}
        return Response(FeatureChatResponseSerializer(data).data, status=status.HTTP_201_CREATED)


class FeatureChatAnswerView(APIView):
    """현재 질문에 답변. 다음 질문이 있으면 질문을, 끝났으면 요약을 반환."""

    permission_classes = [IsAuthenticated]

    @extend_schema(
        request=FeatureChatAnswerSerializer,
        responses={
            200: FeatureChatResponseSerializer,
            400: OpenApiResponse(description='현재 질문과 다른 항목, 답변 누락'),
            404: OpenApiResponse(description='없는 대화'),
            409: OpenApiResponse(description='이미 종료된 대화'),
        },
    )
    def post(self, request, chat_id):
        chat = _get_own_chat(request, chat_id)
        serializer = FeatureChatAnswerSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        try:
            question, finished = feature_chat.answer(chat, data['step'], data['answer'], data['is_skipped'])
        except feature_chat.ChatFinished:
            return _chat_finished_response()
        except feature_chat.WrongStep as exc:
            return Response(
                {'detail': f'현재 질문 항목({exc.current_step})에 대한 답변이 아닙니다.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if finished:
            payload = _finished_payload(chat.id, *finished)
        else:
            payload = {'chat_id': chat.id, 'question': question, 'is_finished': False}
        return Response(FeatureChatResponseSerializer(payload).data, status=status.HTTP_200_OK)


class FeatureChatFinishView(APIView):
    """사용자가 대화를 중간에 끝냄. 그때까지의 답변으로 요약 생성."""

    permission_classes = [IsAuthenticated]

    @extend_schema(request=None, responses={200: FeatureChatResponseSerializer})
    def post(self, request, chat_id):
        chat = _get_own_chat(request, chat_id)
        try:
            summary, features = feature_chat.finish(chat)
        except feature_chat.ChatFinished:
            return _chat_finished_response()
        # 명세상 종료 응답에는 question 키가 없음 (serializer는 allow_null 필드를 null로 채우므로 직접 응답)
        payload = {'chat_id': chat.id, 'is_finished': True, 'summary': summary, 'features': features}
        return Response(payload, status=status.HTTP_200_OK)
