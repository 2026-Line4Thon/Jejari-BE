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
