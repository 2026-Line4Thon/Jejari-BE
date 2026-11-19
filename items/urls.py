from django.urls import path
from .views import (
    HomeView,
    FoundItemListCreateView,
    FoundItemDetailView,
    FeatureChatAnswerView,
    FeatureChatFinishView,
    FeatureChatStartView,
    ItemImageAnalyzeView,
    LostItemCreateView,
    LostItemDetailView,
)

urlpatterns = [
    path('home', HomeView.as_view(), name='home'),
    path('items/found', FoundItemListCreateView.as_view(), name='found-item-list'),
    path('items/found/<int:item_id>', FoundItemDetailView.as_view(), name='found-item-detail'),
    path(
        'items/found/images/analyze',
        ItemImageAnalyzeView.as_view(
            timeout_message='분석 시간이 초과되었습니다. 물건 정보를 직접 입력해 주세요.'
        ),
        name='found-image-analyze',
    ),
    path('items/lost', LostItemCreateView.as_view(), name='lost-item-create'),
    path('items/lost/<int:item_id>', LostItemDetailView.as_view(), name='lost-item-detail'),
    path('items/lost/images/analyze', ItemImageAnalyzeView.as_view(), name='lost-image-analyze'),
    path('items/lost/feature-chats', FeatureChatStartView.as_view(), name='feature-chat-start'),
    path(
        'items/lost/feature-chats/<int:chat_id>/answers',
        FeatureChatAnswerView.as_view(),
        name='feature-chat-answer',
    ),
    path(
        'items/lost/feature-chats/<int:chat_id>/finish',
        FeatureChatFinishView.as_view(),
        name='feature-chat-finish',
    ),
]
