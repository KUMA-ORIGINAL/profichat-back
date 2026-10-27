from django.db import transaction
from django.db.models import Q
from django.utils import timezone

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


def unread_count(chat, user_id, last_read=None) -> int:
    """
    Непрочитанные для участника `user_id`: обычные сообщения собеседника после `last_read`
    (None — с начала чата). Системные и звонковые сообщения не считаются.
    Общее правило для «прочитано» и импорта истории из GetStream.
    """
    companion_id = chat.specialist_id if chat.client_id == user_id else chat.client_id
    qs = _messages_after(chat, last_read) if last_read is not None else Message.objects.filter(chat=chat)
    return qs.filter(sender_id=companion_id, type=Message.Type.REGULAR).count()


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
        member.unread_count = unread_count(chat, user.pk, message)
        member.read_changed_at = timezone.now()  # повторный импорт из GetStream позицию больше не трогает
        member.save(update_fields=["last_read_message_id", "unread_count", "read_changed_at", "updated_at"])
        events.publish(
            [companion_id, user.pk],
            "chat.read",
            {"channel_id": chat.channel_id, "user_id": user.pk, "last_read_message_id": message.id},
        )
    return member


def _message_before(chat, message):
    """Последнее сообщение чата строго до `message` в порядке ленты (created_at, id) или None."""
    return (
        Message.objects.filter(chat=chat)
        .filter(Q(created_at__lt=message.created_at) | Q(created_at=message.created_at, id__lt=message.id))
        .order_by("-created_at", "-id")
        .first()
    )


def _moves_back(chat, member, new_position) -> bool:
    """Строго ли раньше текущей позиции «прочитано» новая (`None` — начало чата)."""
    if member.last_read_message_id is None:
        return False  # ничего не прочитано — назад некуда
    current = Message.objects.filter(chat=chat, pk=member.last_read_message_id).first()
    if current is None:
        return True  # позиция указывает на исчезнувшее сообщение — разрешаем переставить
    return new_position is None or _position(new_position) < _position(current)


def mark_unread(chat, user, message_id: int) -> ChatMember:
    """
    «Пометить непрочитанным начиная с сообщения message_id» — явное исключение из правила «только вперёд».

    last_read_message_id = последнее сообщение строго до message_id (None, если его нет),
    unread_count пересчитывается по общему правилу `unread_count`. Удалённое сообщение — 404.
    Только назад: если новая позиция не раньше текущей (в т.ч. ничего не прочитано), ничего не меняется,
    возвращается текущее состояние без события.
    Событие `chat.unread` уходит только своим устройствам; собеседник не уведомляется
    (его `companionLastReadMessageId` в REST покажет новое значение).
    """
    message = Message.objects.filter(chat=chat, pk=message_id, deleted_at__isnull=True).first()
    if message is None:
        raise AppError("Сообщение не найдено", code=ErrorCode.MESSAGE_NOT_FOUND, status_code=404)

    with transaction.atomic():
        member = ChatMember.objects.select_for_update().get(chat=chat, user_id=user.pk)
        previous = _message_before(chat, message)
        if not _moves_back(chat, member, previous):
            return member
        member.last_read_message_id = previous.id if previous else None
        member.unread_count = unread_count(chat, user.pk, previous)
        member.read_changed_at = timezone.now()  # повторный импорт из GetStream позицию больше не трогает
        member.save(update_fields=["last_read_message_id", "unread_count", "read_changed_at", "updated_at"])
        events.publish(
            [user.pk],
            "chat.unread",
            {
                "channel_id": chat.channel_id,
                "last_read_message_id": member.last_read_message_id,
                "unread_count": member.unread_count,
            },
        )
    return member
