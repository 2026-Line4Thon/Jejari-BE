from django.urls import path
from .views import (
    HomeView,
    FoundItemListView,
    FoundItemDetailView,
    ItemImageAnalyzeView,
)

urlpatterns = [
    path('home', HomeView.as_view(), name='home'),
    path('items/found', FoundItemListView.as_view(), name='found-item-list'),
    path('items/found/<int:item_id>', FoundItemDetailView.as_view(), name='found-item-detail'),
    path(
        'items/found/images/analyze',
        ItemImageAnalyzeView.as_view(
            timeout_message='분석 시간이 초과되었습니다. 물건 정보를 직접 입력해 주세요.'
        ),
        name='found-image-analyze',
    ),
    path('items/lost/images/analyze', ItemImageAnalyzeView.as_view(), name='lost-image-analyze'),
]
