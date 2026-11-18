from rest_framework import serializers
from django.contrib.auth import get_user_model
from items.models import LostItem, FoundItem

User = get_user_model()

class EmailSendSerializer(serializers.Serializer):
    email = serializers.EmailField(
        required=True,
        error_messages={
            'required': '이 필드는 필수 항목입니다.',
            'blank': '이 필드는 필수 항목입니다.',
            'invalid': '올바른 이메일 형식이 아닙니다.',
        }
    )

    def validate_email(self, value):
        # 학교 도메인 검증 (@ac.kr 또는 .edu 등)
        allowed_domains = ('.ac.kr', '.edu')
        if not value.lower().endswith(allowed_domains):
            raise serializers.ValidationError("유효한 학교 이메일(@ac.kr 등) 형식이 아닙니다.")
        return value.lower()


class EmailVerifySerializer(serializers.Serializer):
    email = serializers.EmailField(
        required=True,
        error_messages={
            'required': '이 필드는 필수 항목입니다.',
            'blank': '이 필드는 필수 항목입니다.',
        }
    )
    code = serializers.CharField(
        required=True,
        max_length=6,
        error_messages={
            'required': '이 필드는 필수 항목입니다.',
            'blank': '이 필드는 필수 항목입니다.',
        }
    )


class LogoutSerializer(serializers.Serializer):
    refresh_token = serializers.CharField(
        required=True,
        error_messages={
            'required': '이 필드는 필수 항목입니다.',
            'blank': '이 필드는 필수 항목입니다.',
        }
    )

class MyProfileSerializer(serializers.ModelSerializer):
    is_university_verified = serializers.BooleanField(source='is_verified', read_only=True)

    class Meta:
        model = User
        fields = [
            'id',
            'nickname',
            'email',
            'is_university_verified',
            'university_name',
            'created_at',
        ]


class MyItemSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    item_type = serializers.CharField()
    item_name = serializers.CharField()
    thumbnail_url = serializers.CharField(allow_null=True)
    status = serializers.CharField()
    status_label = serializers.CharField()
    created_at = serializers.DateTimeField()


class MyHistorySerializer(serializers.Serializer):
    chat_room_id = serializers.IntegerField()
    role = serializers.CharField()
    item_id = serializers.IntegerField()
    item_name = serializers.CharField()
    blurred_image_url = serializers.CharField(allow_null=True)
    status = serializers.CharField()
    completed_at = serializers.DateTimeField()