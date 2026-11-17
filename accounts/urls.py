from django.urls import path
from .views import EmailSendView, EmailVerifyView, LogoutView, MyProfileView, MyItemListView, MyItemStatusView, MyHistoryView

urlpatterns = [
    path('email/send', EmailSendView.as_view(), name='email-send'),
    path('email/verify', EmailVerifyView.as_view(), name='email-verify'),
    path('logout', LogoutView.as_view(), name='logout'),
    path('me', MyProfileView.as_view(), name='my-profile'),
    path('me/items', MyItemListView.as_view(), name='my-items'),
    path('me/items/<int:item_id>/status', MyItemStatusView.as_view(), name='my-item-status'),
    path('me/history', MyHistoryView.as_view(), name='my-history'),
]