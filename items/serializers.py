from django.utils import timezone
from rest_framework import serializers
from rest_framework.exceptions import APIException, NotFound

from places.models import Place

from .models import FeatureChat, FoundItem, ItemImage, LostItem


# 1. 홈 화면 & 전체 목록 공용 습득물 카드 Serializer
class FoundItemListSerializer(serializers.ModelSerializer):
    blurred_image_url = serializers.CharField(source='image.image_url', read_only=True)
    found_location = serializers.CharField(source='location_text', read_only=True)

    class Meta:
        model = FoundItem
        fields = [
            'id',
            'blurred_image_url',
            'item_name',
            'found_location',
            'created_at',
        ]


# 2. 습득물 상세 조회 Serializer (private_features, 원본 이미지 키, 임베딩 제외)
class FoundItemDetailSerializer(serializers.ModelSerializer):
    blurred_image_url = serializers.CharField(source='image.image_url', read_only=True)
    found_location = serializers.CharField(source='location_text', read_only=True)
    place_id = serializers.IntegerField(read_only=True)
    storage_status = serializers.CharField(source='get_storage_status_display', read_only=True)

    class Meta:
        model = FoundItem
        fields = [
            'id',
            'blurred_image_url',
            'category',
            'item_name',
            'color',
            'brand',
            'place_id',
            'found_location',
            'found_at',
            'storage_status',
            'storage_location',
            'created_at',
        ]


# ---------------------------------------------------------------------------
# 사진 분석 (POST /items/lost/images/analyze, /items/found/images/analyze)
# ---------------------------------------------------------------------------

class ImageAnalyzeRequestSerializer(serializers.Serializer):
    # 형식·용량 오류는 명세상 detail 메시지로 내려주므로 뷰에서 검사
    image = serializers.FileField()


class ImageTagsSerializer(serializers.Serializer):
    category = serializers.CharField(allow_null=True)
    item_name = serializers.CharField(allow_null=True)
    color = serializers.CharField(allow_null=True)
    brand = serializers.CharField(allow_null=True)
    features = serializers.ListField(child=serializers.CharField())


class ImageAnalyzeResponseSerializer(serializers.Serializer):
    image_id = serializers.IntegerField()
    image_url = serializers.CharField()
    is_blurred = serializers.BooleanField()
    tags = ImageTagsSerializer()
    unrecognized_fields = serializers.ListField(
        child=serializers.CharField(), help_text='AI가 인식하지 못해 null로 내려준 항목'
    )


# ---------------------------------------------------------------------------
# 분실물·습득물 등록 (POST /items/lost, /items/found) · 분실물 결과 조회 (GET /items/lost/<id>)
# ---------------------------------------------------------------------------

class BadRequest(APIException):
    """명세상 {"detail": "..."} 형태로 내려주는 400 오류."""

    status_code = 400
    default_code = 'bad_request'


def _blank_to_none(value):
    if isinstance(value, str):
        value = value.strip()
    return value or None


class ItemCreateBaseSerializer(serializers.Serializer):
    """분실물·습득물 등록 공통 입력. 사용자가 확인·수정한 값이 AI 분석값보다 우선."""

    NULLABLE_TEXT_FIELDS = ('color', 'brand', 'description', 'location_detail')

    category = serializers.CharField(max_length=100)
    item_name = serializers.CharField(max_length=100)
    color = serializers.CharField(max_length=50, required=False, allow_null=True, allow_blank=True)
    brand = serializers.CharField(max_length=50, required=False, allow_null=True, allow_blank=True)
    features = serializers.ListField(
        child=serializers.CharField(max_length=100), required=False, max_length=10
    )
    description = serializers.CharField(
        max_length=1000, required=False, allow_null=True, allow_blank=True
    )
    place_id = serializers.IntegerField()
    location_detail = serializers.CharField(
        max_length=100, required=False, allow_null=True, allow_blank=True
    )

    def normalize(self, attrs):
        for key in self.NULLABLE_TEXT_FIELDS:
            attrs[key] = _blank_to_none(attrs.get(key))
        attrs['features'] = [f.strip() for f in attrs.get('features') or [] if f.strip()]

    def resolve_image_and_place(self, attrs, image_id):
        """본인이 올린 사진과 장소를 객체로 바꿔 attrs에 넣음. 없으면 404."""
        user = self.context['request'].user
        image = ItemImage.objects.filter(id=image_id, uploader=user).first() if image_id else None
        place = Place.objects.filter(id=attrs.pop('place_id')).first()
        if (image_id and image is None) or place is None:
            raise NotFound('이미지 또는 장소를 찾을 수 없습니다.')
        attrs['image'] = image
        attrs['place'] = place


class LostItemCreateSerializer(ItemCreateBaseSerializer):
    image_id = serializers.IntegerField(required=False, allow_null=True)
    feature_chat_id = serializers.IntegerField(required=False, allow_null=True)
    lost_from = serializers.DateTimeField()
    lost_to = serializers.DateTimeField(required=False, allow_null=True)

    def validate(self, attrs):
        self.normalize(attrs)

        image_id = attrs.pop('image_id', None)
        if not image_id and not attrs['description']:
            raise BadRequest('사진 또는 물건 설명 중 하나 이상을 입력해 주세요.')

        attrs['lost_to'] = attrs.get('lost_to') or attrs['lost_from']
        if attrs['lost_from'] > attrs['lost_to']:
            raise BadRequest('분실 시작 시각은 끝 시각보다 앞서야 합니다.')

        self.resolve_image_and_place(attrs, image_id)

        user = self.context['request'].user
        feature_chat_id = attrs.pop('feature_chat_id', None)
        attrs['feature_chat'] = None
        if feature_chat_id:
            attrs['feature_chat'] = FeatureChat.objects.filter(id=feature_chat_id, user=user).first()
            if attrs['feature_chat'] is None:
                raise NotFound('AI 특징 구체화 대화를 찾을 수 없습니다.')
        return attrs


class FoundItemCreateSerializer(ItemCreateBaseSerializer):
    NULLABLE_TEXT_FIELDS = (
        *ItemCreateBaseSerializer.NULLABLE_TEXT_FIELDS, 'storage_location', 'private_features',
    )

    image_id = serializers.IntegerField()
    found_at = serializers.DateTimeField()
    storage_status = serializers.ChoiceField(choices=FoundItem.StorageStatus.choices)
    storage_location = serializers.CharField(
        max_length=100, required=False, allow_null=True, allow_blank=True
    )
    private_features = serializers.CharField(
        max_length=1000, required=False, allow_null=True, allow_blank=True
    )

    def validate_found_at(self, value):
        if value > timezone.now():
            raise serializers.ValidationError('습득 시각은 현재보다 이후일 수 없습니다.')
        return value

    def validate(self, attrs):
        self.normalize(attrs)

        if attrs['storage_status'] == FoundItem.StorageStatus.HANDED_OVER:
            if not attrs['storage_location']:
                raise serializers.ValidationError(
                    {'storage_location': ['인계한 경우 보관 장소를 입력해 주세요.']}
                )
        else:
            attrs['storage_location'] = None  # 직접 보관이면 보관 장소 없음

        self.resolve_image_and_place(attrs, attrs.pop('image_id'))
        return attrs


class LostItemCreateResponseSerializer(serializers.Serializer):
    lost_item_id = serializers.IntegerField()
    status = serializers.CharField()
    message = serializers.CharField()


class FoundItemCreateResponseSerializer(serializers.Serializer):
    found_item_id = serializers.IntegerField()
    status = serializers.CharField()
    message = serializers.CharField()


class PlaceSummarySerializer(serializers.Serializer):
    place_id = serializers.IntegerField(source='id')
    name = serializers.CharField()


class LostItemDetailSerializer(serializers.ModelSerializer):
    lost_item_id = serializers.IntegerField(source='id')
    image_url = serializers.SerializerMethodField()
    summary = serializers.CharField(source='description')
    place = PlaceSummarySerializer()
    candidate_count = serializers.SerializerMethodField()

    class Meta:
        model = LostItem
        fields = [
            'lost_item_id', 'image_url', 'category', 'item_name', 'color', 'brand',
            'features', 'summary', 'place', 'location_detail', 'lost_from', 'lost_to',
            'status', 'candidate_count', 'created_at',
        ]

    def get_image_url(self, obj) -> str | None:
        if obj.image is None:
            return None
        return self.context['request'].build_absolute_uri(obj.image.image_url)

    def get_candidate_count(self, obj) -> int:
        from matching.models import MatchCandidate

        return obj.candidates.filter(status__in=MatchCandidate.ACTIVE_STATUSES).count()
