from rest_framework import serializers

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