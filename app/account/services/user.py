import uuid

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.contrib.auth import get_user_model

from account.models import WorkSchedule
from account.serializers import UserMeSerializer, WorkScheduleSerializer
from chat_access.models import Chat

User = get_user_model()


def generate_unique_username():
    return f"user_{uuid.uuid4().hex[:10]}"


def broadcast_user_update(user, changes=None):
    """
    Отправить обновлённые данные пользователя во все чаты, где он состоит.
    changes -- iterable с именами изменённых полей (или словарь old/new при желании)
    """

    # сериализуем пользователя
    user_data = UserMeSerializer(user).data
    # сериализуем расписание (может быть queryset)
    schedule_qs = WorkSchedule.objects.filter(user=user)
    schedule_data = WorkScheduleSerializer(schedule_qs, many=True).data

    payload = {
        "user": user_data,
        "changes": list(changes) if changes else [],
        "schedule": schedule_data,
    }

    chats = Chat.objects.filter(client=user) | Chat.objects.filter(specialist=user)
    layer = get_channel_layer()

    for chat in chats:
        async_to_sync(layer.group_send)(
            f"chat_{chat.channel_id}",
            {
                "type": "user_update",
                **payload,
            }
        )
