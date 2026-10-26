import base64
import binascii
import logging
from datetime import datetime
from uuid import UUID

from django.db import IntegrityError, transaction
from django.db.models import F, Q
from django.utils import timezone

from chat_access.models import Chat
from common.errors import AppError, ErrorCode
from messenger import tasks
from messenger.models import ChatMember, Message
from messenger.serializers import MessageSerializer
from messenger.services import attachments as attachment_service, events

logger = logging.getLogger(__name__)

DEFAULT_LIMIT = 50
MAX_LIMIT = 100


# --- события ---

def chat_user_ids(chat) -> list[int]:
    return [chat.client_id, chat.specialist_id]


def serialize_message(message) -> dict:
    """JSON-готовое представление сообщения (для событий и ответов)."""
    return MessageSerializer(message).data


def _publish_message(chat, message, event_type) -> None:
    events.publish(chat_user_ids(chat), event_type, serialize_message(message))


def _schedule_push(message_id) -> None:
    tasks.send_message_push.delay(message_id)


# --- создание ---

def _message_empty():
    return AppError("Сообщение не может быть пустым", code=ErrorCode.MESSAGE_EMPTY, status_code=400)


def _edit_forbidden():
    return AppError(
        "Это сообщение нельзя изменить",
        code=ErrorCode.MESSAGE_EDIT_FORBIDDEN,
        status_code=403,
    )


def _apply_new_message(chat, message) -> None:
    """Общие side-effects нового сообщения: последнее сообщение чата и возврат чата из soft-delete."""
    Chat.objects.filter(pk=chat.pk).filter(
        Q(last_message_at__isnull=True) | Q(last_message_at__lte=message.created_at)
    ).update(last_message=message, last_message_at=message.created_at)
    # Как `show` в Stream: новое сообщение возвращает скрытый чат обеим сторонам
    Chat.objects.filter(pk=chat.pk).filter(
        Q(deleted_by_client_at__isnull=False) | Q(deleted_by_specialist_at__isnull=False)
    ).update(deleted_by_client_at=None, deleted_by_specialist_at=None)
    chat.refresh_from_db(
        fields=["last_message", "last_message_at", "deleted_by_client_at", "deleted_by_specialist_at"]
    )


def send_message(
    chat,
    sender,
    *,
    text: str,
    client_msg_id: UUID | None = None,
    reply_to_id: int | None = None,
    attachment_ids: list[UUID] | None = None,
) -> Message:
    """
    Отправка обычного сообщения участником чата.

    Тариф здесь не проверяется (Ruling 1): это делают вьюхи через `access.ensure_can_send`.
    Повтор с тем же `client_msg_id` возвращает уже созданное сообщение без событий и пушей.
    """
    text = (text or "").strip()
    attachment_ids = list(attachment_ids or [])
    if not text and not attachment_ids:
        raise _message_empty()

    if client_msg_id is not None:
        existing = _find_by_client_msg_id(chat, sender, client_msg_id)
        if existing is not None:
            return existing

    reply_to = None
    if reply_to_id is not None:
        reply_to = Message.objects.filter(chat=chat, pk=reply_to_id).first()
        if reply_to is None:
            raise AppError(
                "Сообщение для ответа не найдено в этом чате",
                code=ErrorCode.MESSAGE_NOT_FOUND,
                status_code=400,
            )

    with transaction.atomic():
        try:
            with transaction.atomic():
                message = Message.objects.create(
                    chat=chat,
                    sender=sender,
                    type=Message.Type.REGULAR,
                    text=text,
                    reply_to=reply_to,
                    client_msg_id=client_msg_id,
                )
        except IntegrityError:
            # гонка двух одинаковых запросов: второй упирается в уникальный индекс
            existing = _find_by_client_msg_id(chat, sender, client_msg_id) if client_msg_id else None
            if existing is None:
                raise
            return existing

        if attachment_ids:
            claimed = attachment_service.claim_for_message(chat, sender, attachment_ids)
            attachment_service.attach_to_message(message, claimed)

        _apply_new_message(chat, message)
        ChatMember.objects.filter(chat=chat).exclude(user_id=sender.pk).update(
            unread_count=F("unread_count") + 1
        )
        _publish_message(chat, message, "message.new")
        transaction.on_commit(lambda: _schedule_push(message.id), robust=True)
    return message


def find_by_client_msg_id(chat, sender, client_msg_id) -> Message | None:
    """Уже созданное сообщение с таким `client_msg_id` (для идемпотентного повтора)."""
    return _find_by_client_msg_id(chat, sender, client_msg_id)


def _find_by_client_msg_id(chat, sender, client_msg_id):
    return (
        Message.objects.select_related("chat", "reply_to")
        .filter(chat=chat, sender=sender, client_msg_id=client_msg_id)
        .first()
    )


def create_system_message(chat, custom_type: str, text: str, extra_data: dict | None = None) -> Message:
    """Системное сообщение (sender=None): те же side-effects, что у обычного, но без пуша и без unread."""
    with transaction.atomic():
        message = Message.objects.create(
            chat=chat,
            sender=None,
            type=Message.Type.SYSTEM,
            custom_type=custom_type,
            text=text or "",
            extra_data=extra_data or {},
        )
        _apply_new_message(chat, message)
        _publish_message(chat, message, "message.new")
    return message


# --- изменение ---

def _ensure_editable(message, user) -> None:
    if (
        message.sender_id is None
        or message.sender_id != user.pk
        or message.type != Message.Type.REGULAR
        or message.deleted_at is not None
    ):
        raise _edit_forbidden()


def edit_message(message, user, text) -> Message:
    _ensure_editable(message, user)
    text = (text or "").strip()
    if not text and not message.attachments.exists():
        raise _message_empty()
    message.text = text
    message.edited_at = timezone.now()
    with transaction.atomic():
        message.save(update_fields=["text", "edited_at"])
        _publish_message(message.chat, message, "message.updated")
    return message


def delete_message(message, user) -> Message:
    """Мягкое удаление: текст и вложения скрываются при выдаче."""
    if message.deleted_at is not None and message.sender_id == user.pk:
        return message
    _ensure_editable(message, user)
    message.deleted_at = timezone.now()
    with transaction.atomic():
        message.save(update_fields=["deleted_at"])
        _publish_message(message.chat, message, "message.updated")
    return message


# --- история ---

def _param_invalid(message):
    return AppError(message, code=ErrorCode.PARAM_INVALID, status_code=400)


def encode_cursor(message) -> str:
    raw = f"{message.created_at.isoformat()}|{message.id}".encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def decode_cursor(cursor: str) -> tuple[datetime, int]:
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        raw = base64.urlsafe_b64decode(padded.encode()).decode()
        created_at_raw, id_raw = raw.split("|", 1)
        created_at = datetime.fromisoformat(created_at_raw)
        message_id = int(id_raw)
    except (ValueError, TypeError, UnicodeError, binascii.Error):
        raise _param_invalid("Некорректный курсор")
    if timezone.is_naive(created_at):
        raise _param_invalid("Некорректный курсор")
    return created_at, message_id


def list_messages(
    chat, *, before: str | None = None, after: str | None = None, limit: int = DEFAULT_LIMIT
) -> tuple[list[Message], bool, str | None]:
    """
    История по курсору (created_at, id).

    Без курсора и с `before` — от новых к старым; с `after` — от старых к новым.
    `next_cursor` — курсор последнего отданного сообщения (для следующей страницы в том же направлении).
    """
    if before and after:
        raise _param_invalid("Нельзя передавать before и after одновременно")
    limit = max(1, min(int(limit), MAX_LIMIT))

    qs = Message.objects.filter(chat=chat).select_related("chat", "reply_to").prefetch_related("attachments")
    if after:
        created_at, message_id = decode_cursor(after)
        qs = qs.filter(
            Q(created_at__gt=created_at) | Q(created_at=created_at, id__gt=message_id)
        ).order_by("created_at", "id")
    else:
        if before:
            created_at, message_id = decode_cursor(before)
            qs = qs.filter(Q(created_at__lt=created_at) | Q(created_at=created_at, id__lt=message_id))
        qs = qs.order_by("-created_at", "-id")

    items = list(qs[: limit + 1])
    has_more = len(items) > limit
    items = items[:limit]
    next_cursor = encode_cursor(items[-1]) if items else None
    return items, has_more, next_cursor
