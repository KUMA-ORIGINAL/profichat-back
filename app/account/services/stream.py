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
                "clientId": chat.client.id,
                "specialistId": chat.specialist.id,
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


ALLOWED_TYPES = [
    'tariffProvided',
    'tariffExpired',
    'tariffActivated',
    'chatBlocked'
]

DEFAULT_TEXTS = {
    'tariffProvided': "Доступ по тарифу предоставлен.",
    'tariffExpired': "Срок действия тарифа истёк.",
    'tariffActivated': "Тариф активирован.",
    'chatBlocked': "Чат заблокирован.",
}


def send_system_message_once(channel_id, custom_type: str, text: str = None):
    """
    Отправляет системное сообщение в канал Stream, если такого типа ещё не было последним.
    custom_type: один из ALLOWED_TYPES
    text: если не задан, используется дефолтное сообщение
    Возвращает True если отправлено, False если не отправлено
    """
    if custom_type not in ALLOWED_TYPES:
        logger.warning(f"[Stream] Недопустимый тип system message: {custom_type}")
        return False

    if not text:
        text = DEFAULT_TEXTS[custom_type]

    try:
        channel = chat_client.channel("messaging", channel_id, data={
            'created_by_id': 'system'
        })

        try:
            channel.update_partial({'lastTariffStatusMessage': custom_type})
        except Exception as e_update:
            logger.info(f"[Stream] Не удалось обновить lastTariffStatusMessage: {e_update}")

        messages = channel.query(limit=1, sort=[{'field': 'created_at', 'direction': -1}])['messages']

        if messages:
            msg = messages[0]
            if msg.get('type') == 'system':
                msg_custom_type = (
                    msg.get('custom_type') or
                    msg.get('customType') or
                    msg.get('extraData', {}).get('customType') or
                    msg.get('extraData', {}).get('custom_type')
                )
                if msg_custom_type == custom_type:
                    logger.info(f"[Stream] System message '{custom_type}' уже последнее в канале {channel_id}")
                    return False

        message_data = {
            'text': text,
            'type': 'system',
            'custom_type': custom_type,
            'extraData': {
                'customType': custom_type,
                'custom_type': custom_type
            }
        }

        channel.send_message(message_data, user_id='system')
        logger.info(f"[Stream] System message '{custom_type}' отправлено в канал {channel_id}")
        return True

    except Exception as e:
        logger.warning(f"[Stream] Ошибка отправки system message: {e}")
        return False
