from django.conf import settings
from django.core.paginator import Paginator, EmptyPage
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework import status

from ai.images import InvalidImage
from matching.models import MatchCandidate

from .models import FoundItem, ItemStatus
from .serializers import (
    FoundItemListSerializer,
    FoundItemDetailSerializer,
    ImageAnalyzeRequestSerializer,
    ImageAnalyzeResponseSerializer,
)
from .services import AnalysisUnavailable, NoItemDetected, create_analyzed_image


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
