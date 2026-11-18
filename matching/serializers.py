"""
매칭 후보 응답 (F-02, F-03). 숫자 점수(total_score)와 습득물의 private_features는 내려주지 않습니다.
"""

from rest_framework import serializers

from .models import MatchCandidate


class CandidateFoundItemSerializer(serializers.Serializer):
    found_item_id = serializers.IntegerField(source='id')
    image_url = serializers.SerializerMethodField()
    category = serializers.CharField()
    item_name = serializers.CharField()
    color = serializers.CharField(allow_null=True)
    place_name = serializers.CharField(source='place.name')
    found_at = serializers.DateTimeField()

    def get_image_url(self, obj) -> str:
        return self.context['request'].build_absolute_uri(obj.image.image_url)


class CandidateFoundItemDetailSerializer(CandidateFoundItemSerializer):
    brand = serializers.CharField(allow_null=True)
    features = serializers.ListField(child=serializers.CharField())

    def to_representation(self, instance):
        data = super().to_representation(instance)
        data['features'] = instance.features or []
        # 명세 필드 순서: ... color, brand, features, place_name, found_at
        order = ['found_item_id', 'image_url', 'category', 'item_name', 'color', 'brand',
                 'features', 'place_name', 'found_at']
        return {key: data[key] for key in order}


class CandidateListItemSerializer(serializers.ModelSerializer):
    candidate_id = serializers.IntegerField(source='id')
    similarity_label = serializers.CharField(source='get_similarity_label_display')
    found_item = CandidateFoundItemSerializer()

    class Meta:
        model = MatchCandidate
        fields = ['candidate_id', 'similarity_label', 'status', 'found_item']


class ReasonSerializer(serializers.Serializer):
    field = serializers.CharField()
    is_match = serializers.BooleanField()
    text = serializers.CharField()


class CandidateDetailSerializer(serializers.ModelSerializer):
    candidate_id = serializers.IntegerField(source='id')
    similarity_label = serializers.CharField(source='get_similarity_label_display')
    found_item = CandidateFoundItemDetailSerializer()
    reasons = ReasonSerializer(source='match_reasons', many=True)

    class Meta:
        model = MatchCandidate
        fields = ['candidate_id', 'similarity_label', 'status', 'found_item', 'reasons']


class CandidateListResponseSerializer(serializers.Serializer):
    lost_item_id = serializers.IntegerField()
    status = serializers.CharField()
    candidates = CandidateListItemSerializer(many=True)
    message = serializers.CharField(required=False, help_text='후보가 없을 때만 포함')


class CandidateRejectResponseSerializer(serializers.Serializer):
    candidate_id = serializers.IntegerField()
    status = serializers.CharField()
    message = serializers.CharField()
