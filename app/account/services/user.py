import uuid

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.contrib.auth import get_user_model

from account.serializers import UserMeSerializer
from chat_access.models import Chat

User = get_user_model()


def generate_unique_username():
    return f"user_{uuid.uuid4().hex[:10]}"


def broadcast_user_update(user: User):
    """Отправить обновлённые данные пользователя во все чаты, где он есть"""
    data = UserMeSerializer(user).data  # бери сериализатор, который выдаёт публичные поля
    chats = Chat.objects.filter(client=user) | Chat.objects.filter(specialist=user)

    layer = get_channel_layer()
    for chat in chats:
        async_to_sync(layer.group_send)(
            f"chat_{chat.id}",
            {
                "type": "user_update",
                "user": data,
            }
        )
