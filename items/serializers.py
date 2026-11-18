from rest_framework import serializers

from .models import FoundItem


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
