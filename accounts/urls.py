from django.urls import path
from .views import EmailSendView, EmailVerifyView, LogoutView, MyProfileView, MyItemListView, MyItemStatusView, MyHistoryView

urlpatterns = [
    path('email/send', EmailSendView.as_view(), name='email-send'),
    path('email/verify', EmailVerifyView.as_view(), name='email-verify'),
    path('logout', LogoutView.as_view(), name='logout'),
]