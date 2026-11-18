from rest_framework import serializers
from .models import ChatRoom, ChatMessage


class ChatRoomCreateSerializer(serializers.Serializer):
    candidate_id = serializers.IntegerField(
        required=True,
        error_messages={
            'required': '이 필드는 필수 항목입니다.',
            'null': '이 필드는 필수 항목입니다.'
        }
    )


class ChatRoomResponseSerializer(serializers.ModelSerializer):
    chat_room_id = serializers.IntegerField(source='id')
    candidate_id = serializers.IntegerField(source='candidate.id')
    item_summary = serializers.SerializerMethodField()
    partner = serializers.SerializerMethodField()

    class Meta:
        model = ChatRoom
        fields = ['chat_room_id', 'candidate_id', 'item_summary', 'partner', 'status', 'created_at']

    def get_item_summary(self, obj):
        found_item = obj.candidate.found_item
        # 명세서 예시("검정색 무선 이어폰 케이스")처럼 color가 있으면 조합해서 표시
        full_name = f"{found_item.color} {found_item.item_name}".strip() if found_item.color else found_item.item_name
        return {
            "item_name": full_name,
            "blurred_image_url": found_item.image.image_url,
        }

    def get_partner(self, obj):
        request_user = self.context['request'].user
        if request_user == obj.owner:
            return {
                "nickname": getattr(obj.finder, 'nickname', None) or f"익명학우{obj.finder.id}",
                "role": "FINDER"
            }
        return {
            "nickname": getattr(obj.owner, 'nickname', None) or f"익명학우{obj.owner.id}",
            "role": "OWNER"
        }


class ChatMessageSerializer(serializers.ModelSerializer):
    message_id = serializers.IntegerField(source='id')
    sender_id = serializers.IntegerField(source='sender.id')
    is_mine = serializers.SerializerMethodField()

    class Meta:
        model = ChatMessage
        fields = ['message_id', 'sender_id', 'is_mine', 'content', 'created_at']

    def get_is_mine(self, obj):
        return obj.sender == self.context['request'].user


class ChatMessageCreateSerializer(serializers.Serializer):
    content = serializers.CharField(
        required=True,
        allow_blank=False,
        trim_whitespace=True,
        error_messages={
            'required': '메시지 내용은 비어 있을 수 없습니다.',
            'blank': '메시지 내용은 비어 있을 수 없습니다.'
        }
    )