from django.urls import path
from .views import (
    ChatRoomCreateView,
    ChatMessageListCreateView,
    ChatCompleteView,
)

urlpatterns = [
    path('chats', ChatRoomCreateView.as_view(), name='chat-create'),
    path('chats/<int:chat_id>/messages', ChatMessageListCreateView.as_view(), name='chat-messages'),
    path('chats/<int:chat_id>/complete', ChatCompleteView.as_view(), name='chat-complete'),
]