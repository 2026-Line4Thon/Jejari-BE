# accounts/user_urls.py
from django.urls import path
from .views import (
    MyProfileView,
    MyItemListView,
    MyItemStatusView,
    MyHistoryView,
)

urlpatterns = [
    path('me', MyProfileView.as_view(), name='my-profile'),
    path('me/items', MyItemListView.as_view(), name='my-items'),
    path('me/items/<int:item_id>/status', MyItemStatusView.as_view(), name='my-item-status'),
    path('me/history', MyHistoryView.as_view(), name='my-history'),
]