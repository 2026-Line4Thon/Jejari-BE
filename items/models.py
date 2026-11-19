from django.conf import settings
from django.db import models
from pgvector.django import HnswIndex, VectorField

from common.models import BaseModel


class ItemStatus(models.TextChoices):
    """LostItem·FoundItem 공통 진행 상태."""

    WAITING = 'WAITING', '매칭 대기'
    CANDIDATE_FOUND = 'CANDIDATE_FOUND', '후보 있음'
    VERIFYING = 'VERIFYING', '소유권 확인 중'
    CHATTING = 'CHATTING', '채팅 중'
    COMPLETED = 'COMPLETED', '반환 완료'


class ItemImage(BaseModel):
    """업로드 이미지와 AI 분석 결과. 사진 분석 API가 반환하는 image_id."""

    uploader = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='item_images',
    )
    image_url = models.CharField(max_length=500)  # 공개용 (블러 반영)
    original_image_key = models.CharField(max_length=500)  # 비공개 원본 키, 공개 API 응답 금지
    is_blurred = models.BooleanField(default=False)
    ai_tags = models.JSONField(null=True, blank=True)  # 비전 모델 분석 원본

    def __str__(self):
        return f'ItemImage({self.id})'


class BaseItem(BaseModel):
    """분실물·습득물 공통 컬럼."""

    place = models.ForeignKey('places.Place', on_delete=models.PROTECT, related_name='+')
    location_detail = models.CharField(max_length=100, null=True, blank=True)
    category = models.CharField(max_length=100)
    item_name = models.CharField(max_length=100)
    color = models.CharField(max_length=50, null=True, blank=True)
    brand = models.CharField(max_length=50, null=True, blank=True)
    features = models.JSONField(null=True, blank=True)  # ERD 문서 외 추가 컬럼 (외형 특징 목록)
    description = models.TextField()  # 임베딩 원문 설명문
    text_embedding = VectorField(dimensions=settings.EMBEDDING_DIMENSIONS)
    image_embedding = VectorField(dimensions=settings.EMBEDDING_DIMENSIONS, null=True, blank=True)
    status = models.CharField(max_length=20, choices=ItemStatus.choices, default=ItemStatus.WAITING)

    class Meta:
        abstract = True

    @property
    def location_text(self):
        """화면 표시용 장소 문자열 (예: '중앙도서관 2층 열람실')."""
        if self.location_detail:
            return f'{self.place.name} {self.location_detail}'
        return self.place.name


class LostItem(BaseItem):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='lost_items',
    )
    # 텍스트로만 등록하면 NULL. 등록 방식은 image 유무로 판단 (register_type 컬럼 없음)
    image = models.ForeignKey(
        ItemImage,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='lost_items',
    )
    lost_from = models.DateTimeField()
    lost_to = models.DateTimeField()

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['status']),
            HnswIndex(
                name='lost_text_emb_hnsw',
                fields=['text_embedding'],
                m=16,
                ef_construction=64,
                opclasses=['vector_cosine_ops'],
            ),
        ]

    def __str__(self):
        return f'LostItem({self.id}) {self.item_name}'


class FoundItem(BaseItem):
    class StorageStatus(models.TextChoices):
        SELF = 'SELF', '직접 보관 중'
        HANDED_OVER = 'HANDED_OVER', '보관처에 인계'

    finder = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='found_items',
    )
    image = models.ForeignKey(ItemImage, on_delete=models.PROTECT, related_name='found_items')
    found_at = models.DateTimeField()
    storage_status = models.CharField(
        max_length=50,
        choices=StorageStatus.choices,
        default=StorageStatus.SELF,
    )
    storage_location = models.CharField(max_length=100, null=True, blank=True)
    private_features = models.TextField(null=True, blank=True)  # 비공개, 소유권 확인 전용

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['status']),
            HnswIndex(
                name='found_text_emb_hnsw',
                fields=['text_embedding'],
                m=16,
                ef_construction=64,
                opclasses=['vector_cosine_ops'],
            ),
        ]

    def __str__(self):
        return f'FoundItem({self.id}) {self.item_name}'


class FeatureChat(BaseModel):
    """분실물 등록 전 AI 특징 구체화 세션. 등록 시 lost_item 연결."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='feature_chats',
    )
    lost_item = models.ForeignKey(
        LostItem,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='feature_chats',
    )
    # ERD 문서 외 추가 컬럼: 대화를 시작할 때 사용자가 입력한 설명 (요약 생성에 사용)
    input_description = models.TextField(null=True, blank=True)
    summary = models.TextField(null=True, blank=True)
    is_finished = models.BooleanField(default=False)


class FeatureChatTurn(BaseModel):
    # 사진·설명에서 이미 파악한 항목도 턴으로 남김 (question에 이 표시, answer에 값)
    KNOWN_QUESTION = '(사진·설명에서 파악한 정보)'

    class StepCategory(models.TextChoices):
        # 이 순서대로 질문 (순서는 코드로 고정)
        CATEGORY = 'category', '종류'
        COLOR = 'color', '색상'
        SIZE = 'size', '크기'
        MATERIAL = 'material', '재질'
        SHAPE = 'shape', '모양'
        MARKS = 'marks', '흠집·표시'
        BRAND = 'brand', '브랜드'

    chat = models.ForeignKey(FeatureChat, on_delete=models.CASCADE, related_name='turns')
    step_category = models.CharField(max_length=30, choices=StepCategory.choices)
    question = models.TextField()
    answer = models.TextField(null=True, blank=True)
    is_skipped = models.BooleanField(default=False)  # "잘 모르겠어요"

    class Meta:
        ordering = ['created_at', 'id']
