
import logging

from django.conf import settings

from account.services.stream import (
    create_stream_channel,
    show_channel_for_user,
    update_channel_extra_data,
)
from chat_access.models import Chat
from common.errors import AppError, ErrorCode
from messenger.services import ensure_members, events
from messenger.services import messages as message_service

logger = logging.getLogger(__name__)


def send_greeting(chat, specialist) -> None:
    """
    Приветствие специалиста первым сообщением нового чата.

    Отправляется всегда, в обход тарифной проверки (Ruling 1: `send_message` тариф не проверяет).
    Ошибка не ломает создание чата: приветствие — не критичная часть.
    В MESSENGER_LEGACY_MODE без нашего FCM-пуша: старое приложение уже получает пуш приветствия
    от Stream и пуш-приглашение.
    """
    greeting = (specialist.invite_greeting or "").strip()
    if not greeting:
        return
    try:
        message_service.send_message(chat, specialist, text=greeting, push=not settings.MESSENGER_LEGACY_MODE)
    except Exception:
        logger.exception("Failed to send greeting to chat %s", chat.pk)


def create_or_get_chat(client, specialist):
    channel_id = f"chat_{client.id}_{specialist.id}"
    chat, created = Chat.objects.get_or_create(
        client=client,
        specialist=specialist,
        defaults={"channel_id": channel_id},
    )
    ensure_members(chat)
    if created:
        try:
            create_stream_channel(chat, first_message=specialist.invite_greeting)
        except Exception as exc:
            chat.delete()
            raise AppError(
                f"Ошибка создания канала в GetStream: {exc}",
                code=ErrorCode.STREAM_CHANNEL_CREATE_FAILED,
            )
        send_greeting(chat, specialist)
    else:
        update_fields = []
        was_deleted_by_client = chat.deleted_by_client_at is not None
        was_deleted_by_specialist = chat.deleted_by_specialist_at is not None
        if chat.deleted_by_client_at is not None:
            chat.deleted_by_client_at = None
            update_fields.append("deleted_by_client_at")
        if chat.deleted_by_specialist_at is not None:
            chat.deleted_by_specialist_at = None
            update_fields.append("deleted_by_specialist_at")
        if update_fields:
            chat.save(update_fields=update_fields)
            if was_deleted_by_client:
                show_channel_for_user(chat.channel_id, chat.client_id)
            if was_deleted_by_specialist:
                show_channel_for_user(chat.channel_id, chat.specialist_id)
    return chat


def update_chat_and_stream(instance, validated_data):
    for field, value in validated_data.items():
        setattr(instance, field, value)
    instance.save(update_fields=[*validated_data.keys(), "updated_at"])
    events.publish_chat_updated(instance)

    try:
        update_channel_extra_data(channel_id=instance.channel_id, data=validated_data)
    except Exception as exc:
        raise AppError(
            f"Ошибка обновления канала в GetStream: {exc}",
            code=ErrorCode.STREAM_CHANNEL_UPDATE_FAILED,
        )
    return instance
