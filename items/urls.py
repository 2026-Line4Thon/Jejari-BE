from django.urls import path
from .views import (
    HomeView,
    FoundItemListView,
    FoundItemDetailView,
    NotificationListView,
    NotificationReadView,
)

urlpatterns = [
    path('home', HomeView.as_view(), name='home'),
    path('items/found', FoundItemListView.as_view(), name='found-item-list'),
    path('items/found/<int:item_id>', FoundItemDetailView.as_view(), name='found-item-detail'),
    path('notifications', NotificationListView.as_view(), name='notification-list'),
    path('notifications/<int:notification_id>/read', NotificationReadView.as_view(), name='notification-read'),
]