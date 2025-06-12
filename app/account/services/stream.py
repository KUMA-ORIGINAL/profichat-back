import logging

from common.stream_client import chat_client

logger = logging.getLogger(__name__)


def create_stream_channel(chat, first_message: str = None):
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

        if first_message:
            channel.send_message(
                {"text": first_message},
                str(chat.specialist.id)
            )
            logger.info(f"[Stream] Первое сообщение отправлено: {first_message}")

    except Exception as e:
        logger.warning(f"[Stream] Ошибка создания канала: {e}")


def update_channel_extra_data(channel_id: str, data: dict, channel_type: str = "messaging"):
    channel = chat_client.channel(channel_type, channel_id)
    channel.update_partial(data)


def delete_stream_channel(channel_id):
    try:
        channel = chat_client.channel("messaging", channel_id)
        channel.delete()
        logger.info(f"[Stream] Канал успешно удалён: {channel_id}")
    except Exception as e:
        logger.warning(f"[Stream] Ошибка удаления канала: {e}")
