import logging

from chat_access.models import Chat
from common.stream_client import chat_client

logger = logging.getLogger(__name__)

def create_stream_channel(chat: Chat):
    try:
        channel = chat_client.channel(
            channel_type="messaging",
            channel_id=chat.channel_id,
            data={
                "members": [str(chat.client.id), str(chat.specialist.id)],
                "chat_id": chat.id,
            },
        )
        channel.create(str(chat.specialist.id))
        logger.info(f"[Stream] Канал успешно создан: {chat.channel_id}")
    except Exception as e:
        logger.warning(f"[Stream] Ошибка создания канала: {e}")


def update_channel_extra_data(channel_id: str, data: dict, channel_type: str = "messaging"):
    channel = chat_client.channel(channel_type, channel_id)
    channel.update(data)
