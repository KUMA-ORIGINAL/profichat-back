from django.db import transaction
from django.db.models import Q

from common.errors import AppError, ErrorCode
from messenger.models import ChatMember, Message
from messenger.services import events


def _position(message) -> tuple:
    return message.created_at, message.id


def _messages_after(chat, message):
    """Сообщения чата строго после `message` в порядке ленты (created_at, id)."""
    return Message.objects.filter(chat=chat).filter(
        Q(created_at__gt=message.created_at) | Q(created_at=message.created_at, id__gt=message.id)
    )


def mark_read(chat, user, message_id: int) -> ChatMember:
    """
    Отметка «прочитано до сообщения message_id».

    Монотонно: сообщение раньше уже прочитанного (по created_at, id) игнорируется.
    unread_count пересчитывается как число обычных сообщений собеседника после прочитанного
    (системные и звонковые сообщения непрочитанными не считаются).
    Событие `chat.read` уходит собеседнику и себе (синхронизация устройств).
    """
    message = Message.objects.filter(chat=chat, pk=message_id).first()
    if message is None:
        raise AppError("Сообщение не найдено", code=ErrorCode.MESSAGE_NOT_FOUND, status_code=404)

    companion_id = chat.specialist_id if chat.client_id == user.pk else chat.client_id
    with transaction.atomic():
        # блокировка строки участника: параллельная отправка (F()+1) дождётся пересчёта
        member = ChatMember.objects.select_for_update().get(chat=chat, user_id=user.pk)
        if member.last_read_message_id is not None:
            current = Message.objects.filter(chat=chat, pk=member.last_read_message_id).first()
            if current is not None and _position(current) >= _position(message):
                return member

        member.last_read_message_id = message.id
        member.unread_count = (
            _messages_after(chat, message).filter(sender_id=companion_id, type=Message.Type.REGULAR).count()
        )
        member.save(update_fields=["last_read_message_id", "unread_count", "updated_at"])
        events.publish(
            [companion_id, user.pk],
            "chat.read",
            {"channel_id": chat.channel_id, "user_id": user.pk, "last_read_message_id": message.id},
        )
    return member
