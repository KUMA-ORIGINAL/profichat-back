import logging
import uuid
from datetime import datetime, timedelta

from django.conf import settings
from django.utils import timezone

from common.errors import AppError, ErrorCode
from messenger.clients import storage
from messenger.models import Attachment
from messenger.services import access

logger = logging.getLogger(__name__)

UPLOAD_URL_TTL = 15 * 60


def _invalid(message="Вложение недоступно для отправки"):
    return AppError(message, code=ErrorCode.ATTACHMENT_INVALID, status_code=400)


def _max_bytes(kind) -> int:
    return settings.MESSENGER_ATTACHMENT_MAX_BYTES[kind]


def create_upload(
    chat,
    user,
    *,
    kind: str,
    file_name: str,
    mime_type: str,
    size: int,
    width: int | None = None,
    height: int | None = None,
    duration_ms: int | None = None,
    waveform: list | None = None,
) -> tuple[Attachment, str, datetime]:
    """Резервирует вложение и выдаёт presigned PUT-ссылку на 15 минут."""
    access.ensure_can_send(chat, user)
    if kind == Attachment.Kind.VOICE:
        access.ensure_can_send_voice(chat, user)
    if size > _max_bytes(kind):
        raise AppError("Файл слишком большой", code=ErrorCode.ATTACHMENT_TOO_LARGE, status_code=413)

    attachment_id = uuid.uuid4()
    attachment = Attachment.objects.create(
        id=attachment_id,
        uploader=user,
        chat=chat,
        kind=kind,
        object_key=f"chats/{chat.pk}/{attachment_id}/{storage.safe_file_name(file_name)}",
        file_name=file_name,
        mime_type=mime_type,
        size=size,
        width=width,
        height=height,
        duration_ms=duration_ms,
        waveform=waveform,
    )
    upload_url = storage.presigned_put(attachment.object_key, mime_type, UPLOAD_URL_TTL)
    expires_at = timezone.now() + timedelta(seconds=UPLOAD_URL_TTL)
    return attachment, upload_url, expires_at


def claim_for_message(chat, user, attachment_ids) -> list[Attachment]:
    """
    Проверяет вложения перед привязкой к сообщению и помечает их `READY`.

    Каждое должно быть загружено этим пользователем в этот чат, ещё не привязано к сообщению
    и реально лежать в хранилище в пределах лимита своего типа. Вызывается внутри транзакции
    `send_message`; привязку к сообщению выполняет `attach_to_message`. Порядок результата
    совпадает с `attachment_ids`.
    """
    ids = list(attachment_ids)
    if len(set(ids)) != len(ids):
        raise _invalid("Вложения не должны повторяться")

    found = {
        attachment.pk: attachment
        for attachment in Attachment.objects.select_for_update().filter(
            pk__in=ids, chat=chat, uploader=user, message__isnull=True, status=Attachment.Status.PENDING
        )
    }
    if len(found) != len(ids):
        raise _invalid()
    attachments = [found[pk] for pk in ids]

    if any(attachment.kind == Attachment.Kind.VOICE for attachment in attachments):
        access.ensure_can_send_voice(chat, user)

    for position, attachment in enumerate(attachments):
        attachment.position = position
        meta = storage.head(attachment.object_key)
        if meta is None:
            raise _invalid("Файл не загружен")
        actual_size = meta["ContentLength"]
        if actual_size <= 0 or actual_size > _max_bytes(attachment.kind):
            raise _invalid("Недопустимый размер файла")
        attachment.size = actual_size
        attachment.status = Attachment.Status.READY
    return attachments


def attach_to_message(message, attachments) -> None:
    """Сохраняет проверенные `claim_for_message` вложения как принадлежащие сообщению."""
    for attachment in attachments:
        attachment.message = message
        attachment.save(update_fields=["message", "size", "status", "position", "updated_at"])


def cleanup_pending(older_than: timedelta = timedelta(hours=24)) -> int:
    """Удаляет не привязанные к сообщению `PENDING`-вложения старше `older_than` вместе с объектом в хранилище."""
    cutoff = timezone.now() - older_than
    removed = 0
    stale = Attachment.objects.filter(
        status=Attachment.Status.PENDING, message__isnull=True, created_at__lt=cutoff
    )
    for attachment in stale.iterator():
        try:
            storage.delete(attachment.object_key)
        except Exception:
            logger.exception("Не удалось удалить объект вложения %s", attachment.pk)
            continue
        attachment.delete()
        removed += 1
    return removed
