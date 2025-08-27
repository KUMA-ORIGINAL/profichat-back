from django.urls import path

from chat_access import consumers

websocket_urlpatterns = [
    path("ws/chats/<int:chat_id>/", consumers.ChatConsumer.as_asgi()),
]
