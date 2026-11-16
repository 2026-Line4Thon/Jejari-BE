from rest_framework import serializers
from .models import FoundItem, Notification


# 1. 홈 화면 & 전체 목록 공용 습득물 카드 Serializer
class FoundItemListSerializer(serializers.ModelSerializer):
    class Meta:
        model = FoundItem
        fields = [
            'id',
            'blurred_image_url',
            'item_name',
            'found_location',
            'created_at',
        ]


# 2. 습득물 상세 조회 Serializer (비공개 특징 제외)
class FoundItemDetailSerializer(serializers.ModelSerializer):
    class Meta:
        model = FoundItem
        fields = [
            'id',
            'blurred_image_url',
            'category',
            'item_name',
            'color',
            'brand',
            'found_location',
            'found_at',
            'storage_status',
            'created_at',
        ]


# 3. 알림 목록 Serializer
class NotificationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Notification
        fields = [
            'id',
            'type',
            'title',
            'message',
            'target_id',
            'is_read',
            'created_at',
        ]