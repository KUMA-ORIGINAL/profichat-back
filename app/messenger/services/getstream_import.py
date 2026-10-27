"""
Перенос истории переписки из GetStream в свой мессенджер (спека §8).

Каналы обрабатываются по одному. Сообщения канала читаются постранично от старых к новым:
`channel.query(messages={"limit": N, "created_at_after_or_equal": <created_at последнего>})`
(Stream отдаёт страницу по возрастанию времени). Используется `..._or_equal`, а не строгое
`created_at_after`, чтобы не потерять сообщения с тем же временем на границе страницы; повторы
отсекаются по id. Ответы в тредах (`reply_count > 0`) в выдачу канала не попадают — они
дочитываются через `channel.get_replies(parent_id, ...)` тем же способом.

Идемпотентность и возобновляемость: ключ сообщения — `Message.stream_id`, каждое сообщение и
каждое вложение сохраняются сразу (автокоммит), поэтому прерванный импорт можно просто
перезапустить: существующие сообщения пропускаются (обновляются только `deleted_at` и правки),
уже скачанные вложения не скачиваются повторно (id вложения детерминирован: uuid5 от
stream_id сообщения и номера вложения).

Импорт не публикует событий и не шлёт пушей: это история, а не новые сообщения.
"""
import logging
import mimetypes
import time
import uuid
from dataclasses import dataclass, field, fields
from datetime import datetime, timedelta, timezone as dt_timezone
from urllib.parse import unquote, urlparse

import requests
from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Q
from django.utils.dateparse import parse_datetime
from stream_chat.base.exceptions import StreamAPIException

from chat_access.models import Chat
from common import stream_client
from messenger.clients import storage
from messenger.models import Attachment, ChatMember, Message
from messenger.services.members import ensure_members
from messenger.services.read_state import unread_count

logger = logging.getLogger(__name__)
User = get_user_model()

CHANNEL_TYPE = "messaging"
PAGE_SIZE = 100
# Максимальный limit сообщений в одном запросе Stream: страницу расширяем до него, если
# целая страница состоит из сообщений с одинаковым created_at.
MAX_PAGE_SIZE = 300
MAX_ATTEMPTS = 5
EPOCH = "1970-01-01T00:00:00.000000Z"
DOWNLOAD_TIMEOUT = (10, 300)  # connect, read (секунды)
# окно, в котором сообщение из Stream считается тем же, что уже записано в нашу БД двойной записью
DOUBLE_WRITE_WINDOW = timedelta(seconds=60)
ATTACHMENT_NAMESPACE = uuid.UUID("5d0c1b9e-7f0a-4c55-9a43-6a1f4b1f6e21")

SYSTEM_USER_IDS = {"", "system"}
SKIPPED_STREAM_TYPES = {"ephemeral", "error"}
REGULAR_STREAM_TYPES = {"regular", "reply", "deleted"}
UPLOADABLE_KINDS = {
    "image": Attachment.Kind.IMAGE,
    "video": Attachment.Kind.VIDEO,
    "file": Attachment.Kind.FILE,
    "audio": Attachment.Kind.FILE,
    "voiceRecording": Attachment.Kind.VOICE,
}


@dataclass
class ImportStats:
    channels: int = 0
    messages_created: int = 0
    messages_skipped: int = 0
    attachments: int = 0
    errors: list[str] = field(default_factory=list)
    # уже были в БД и обновлены (удаление/правка в Stream)
    messages_updated: int = 0
    # найдены в БД без stream_id (двойная запись переходного периода) и связаны со Stream
    messages_linked: int = 0
    # авторы, которых нет в нашей БД (сообщения сохранены с sender=None)
    unknown_users: int = 0
    # неподдерживаемые вложения (giphy, неизвестный тип) — сохранены в extra_data сообщения
    unknown_attachments: int = 0
    # превью ссылок — пропущены, текст сообщения сохранён
    link_previews: int = 0

    def merge(self, other: "ImportStats") -> None:
        for item in fields(self):
            value = getattr(other, item.name)
            if isinstance(value, list):
                getattr(self, item.name).extend(value)
            else:
                setattr(self, item.name, getattr(self, item.name) + value)

    def summary(self) -> str:
        parts = [
            f"{item.name}={len(getattr(self, item.name)) if item.name == 'errors' else getattr(self, item.name)}"
            for item in fields(self)
        ]
        return " ".join(parts)


class ChannelImportError(Exception):
    pass


# --- утилиты ---

def _parse_ts(value) -> datetime | None:
    if not value:
        return None
    parsed = parse_datetime(value)
    if parsed is None:
        raise ValueError(f"Некорректная дата: {value!r}")
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt_timezone.utc)
    return parsed


def _format_ts(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=dt_timezone.utc)
    return value.astimezone(dt_timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _position(message) -> tuple:
    return message.created_at, message.id


def _with_backoff(func, *args, **kwargs):
    """Вызов Stream API с повтором на 429: пауза 1, 2, 4, 8 с, всего до 5 попыток."""
    for attempt in range(MAX_ATTEMPTS):
        try:
            return func(*args, **kwargs)
        except StreamAPIException as exc:
            if exc.status_code != 429 or attempt == MAX_ATTEMPTS - 1:
                raise
            delay = 2 ** attempt
            logger.warning("Stream rate limit, retry in %s s (attempt %s)", delay, attempt + 1)
            time.sleep(delay)


def _retry_after(response) -> float | None:
    raw = (response.headers or {}).get("Retry-After")
    try:
        return max(float(raw), 0) if raw is not None else None
    except (TypeError, ValueError):
        return None


def _download(url):
    """Потоковый GET файла с повтором на 429 (Retry-After или 2^n с, до 5 попыток)."""
    for attempt in range(MAX_ATTEMPTS):
        response = requests.get(url, stream=True, timeout=DOWNLOAD_TIMEOUT)
        if response.status_code != 429 or attempt == MAX_ATTEMPTS - 1:
            return response
        delay = _retry_after(response)
        response.close()
        time.sleep(delay if delay is not None else 2 ** attempt)


class _CountingReader:
    """Файлоподобная обёртка над потоком ответа: считает реально прочитанные байты."""

    def __init__(self, raw):
        self._raw = raw
        self.count = 0

    def read(self, size=-1):
        chunk = self._raw.read(size)
        self.count += len(chunk)
        return chunk


def _iter_pages(fetch, cursor: str):
    """
    Постраничное чтение от старых к новым. `fetch(options) -> list[message]`.

    Каждое сообщение отдаётся один раз. Если страница целиком состоит из сообщений
    с одним `created_at` (курсор не может сдвинуться), limit увеличивается до MAX_PAGE_SIZE;
    если не помогает — ошибка канала, а не тихая потеря сообщений.
    """
    seen = set()
    limit = PAGE_SIZE
    cursor_ts = _parse_ts(cursor)
    while True:
        page = fetch({"limit": limit, "created_at_after_or_equal": cursor})
        new = [message for message in page if message.get("id") not in seen]
        seen.update(message.get("id") for message in new)
        if new:
            yield new
        if len(page) < limit:
            return
        last_ts = _parse_ts(page[-1].get("created_at"))
        if last_ts != cursor_ts:
            cursor, cursor_ts, limit = page[-1]["created_at"], last_ts, PAGE_SIZE
            continue
        if limit >= MAX_PAGE_SIZE:
            raise ChannelImportError(
                f"Более {MAX_PAGE_SIZE} сообщений с одинаковым created_at={cursor}: пагинация невозможна"
            )
        limit = MAX_PAGE_SIZE


def _custom_type(raw) -> str:
    extra = raw.get("extraData") or raw.get("extra_data") or {}
    return (
        raw.get("custom_type")
        or raw.get("customType")
        or extra.get("customType")
        or extra.get("custom_type")
        or ""
    )


def _waveform(values):
    """Stream хранит waveform_data как float 0..1; наш API — целые 0..100."""
    if not isinstance(values, list) or not values:
        return None
    try:
        numbers = [float(value) for value in values]
    except (TypeError, ValueError):
        return None
    if all(0 <= number <= 1 for number in numbers):
        return [round(number * 100) for number in numbers]
    return [round(number) for number in numbers]


def _positive_int(value):
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number >= 0 else None


def _file_name(attachment, url) -> str:
    name = attachment.get("title") or attachment.get("fallback") or attachment.get("name")
    if not name and url:
        name = unquote(urlparse(url).path.rsplit("/", 1)[-1])
    return (name or "file")[:255]


@dataclass
class _AttachmentSpec:
    index: int
    kind: str
    url: str
    file_name: str
    mime_type: str
    width: int | None = None
    height: int | None = None
    duration_ms: int | None = None
    waveform: list | None = None
    # исходное вложение Stream: при сбое скачивания сохраняется в extra_data сообщения
    raw: dict = field(default_factory=dict)


@dataclass
class _MappedMessage:
    stream_id: str
    type: str
    custom_type: str
    sender_id: int | None
    text: str
    created_at: datetime
    edited_at: datetime | None
    deleted_at: datetime | None
    extra_data: dict
    reply_to_stream_id: str | None
    attachments: list


class _ChannelImporter:
    def __init__(self, chat, stats: ImportStats, dry_run: bool):
        self.chat = chat
        self.stats = stats
        self.dry_run = dry_run
        self.users = {str(chat.client_id): chat.client_id, str(chat.specialist_id): chat.specialist_id}
        self.unknown_users = set()
        self.processed = set()
        self.reply_links = []

    # --- основной цикл ---

    def run(self, since: datetime | None) -> None:
        channel = stream_client.chat_client.channel(CHANNEL_TYPE, self.chat.channel_id)
        if not self.dry_run:
            ensure_members(self.chat)

        read_entries = None
        member_entries = None

        def fetch_channel(options):
            nonlocal read_entries, member_entries
            response = _with_backoff(channel.query, messages=options)
            if read_entries is None:
                read_entries = response.get("read") or []
                member_entries = response.get("members") or []
            return response.get("messages") or []

        cursor = _format_ts(since) if since else EPOCH
        for page in _iter_pages(fetch_channel, cursor):
            self._import_page(page)
            for raw in page:
                if raw.get("reply_count"):
                    self._import_thread(channel, raw["id"], cursor)

        if self.dry_run:
            return
        self._link_replies()
        self._apply_read_state(read_entries or [])
        self._apply_pinned_state(member_entries or [])
        self._update_last_message()

    def _import_thread(self, channel, parent_id, cursor) -> None:
        def fetch_replies(options):
            response = _with_backoff(channel.get_replies, parent_id, **options)
            return response.get("messages") or []

        for page in _iter_pages(fetch_replies, cursor):
            self._import_page(page)

    def _import_page(self, page) -> None:
        stream_ids = [raw["id"] for raw in page if raw.get("id")]
        existing = {message.stream_id: message for message in Message.objects.filter(stream_id__in=stream_ids)}
        for raw in page:
            stream_id = raw.get("id")
            if not stream_id or stream_id in self.processed:
                continue
            self.processed.add(stream_id)
            try:
                self._import_message(raw, existing.get(stream_id))
            except Exception as exc:
                logger.exception("Failed to import message %s of %s", stream_id, self.chat.channel_id)
                self.stats.errors.append(f"{self.chat.channel_id}: message {stream_id}: {exc}")

    # --- сообщение ---

    def _resolve_user(self, stream_user_id) -> int | None:
        stream_user_id = str(stream_user_id or "")
        if stream_user_id in SYSTEM_USER_IDS:
            return None
        if stream_user_id not in self.users:
            user_id = int(stream_user_id) if stream_user_id.isdigit() else None
            if user_id is not None and not User.objects.filter(pk=user_id).exists():
                user_id = None
            self.users[stream_user_id] = user_id
        user_id = self.users[stream_user_id]
        if user_id is None and stream_user_id not in self.unknown_users:
            self.unknown_users.add(stream_user_id)
            self.stats.unknown_users += 1
        return user_id

    def _map(self, raw) -> _MappedMessage | None:
        stream_type = raw.get("type") or "regular"
        if stream_type in SKIPPED_STREAM_TYPES:
            return None

        stream_user_id = str((raw.get("user") or {}).get("id") or raw.get("user_id") or "")
        sender_id = self._resolve_user(stream_user_id)
        extra_data = {}
        if sender_id is None and stream_user_id not in SYSTEM_USER_IDS:
            extra_data["stream_user_id"] = stream_user_id

        custom_type = ""
        if stream_type == "system":
            message_type = Message.Type.SYSTEM
            sender_id = None  # sender=None — признак системного сообщения
            custom_type = _custom_type(raw)
            stream_extra = raw.get("extraData") or {}
            if custom_type:
                extra_data["customType"] = custom_type
            client_name = stream_extra.get("client_name") or stream_extra.get("clientName")
            specialist_name = stream_extra.get("specialist_name") or stream_extra.get("specialistName")
            if client_name is not None:
                extra_data["clientName"] = client_name
            if specialist_name is not None:
                extra_data["specialistName"] = specialist_name
        else:
            message_type = Message.Type.REGULAR
            if stream_type not in REGULAR_STREAM_TYPES:
                extra_data["stream_type"] = stream_type

        deleted_at = _parse_ts(raw.get("deleted_at"))
        if deleted_at is None and stream_type == "deleted":
            deleted_at = _parse_ts(raw.get("updated_at")) or _parse_ts(raw.get("created_at"))

        attachments = []
        for index, attachment in enumerate(raw.get("attachments") or []):
            spec = self._map_attachment(index, attachment)
            if spec is not None:
                attachments.append(spec)
            elif not attachment.get("og_scrape_url"):
                extra_data.setdefault("stream_attachments", []).append(attachment)

        return _MappedMessage(
            stream_id=raw["id"],
            type=message_type,
            custom_type=custom_type,
            sender_id=sender_id,
            text=raw.get("text") or "",
            created_at=_parse_ts(raw.get("created_at")),
            edited_at=_parse_ts(raw.get("message_text_updated_at")),
            deleted_at=deleted_at,
            extra_data=extra_data,
            reply_to_stream_id=raw.get("quoted_message_id") or raw.get("parent_id"),
            attachments=attachments,
        )

    def _map_attachment(self, index, attachment) -> _AttachmentSpec | None:
        if attachment.get("og_scrape_url"):
            self.stats.link_previews += 1
            return None
        stream_type = attachment.get("type")
        kind = UPLOADABLE_KINDS.get(stream_type)
        url = attachment.get("asset_url") or (attachment.get("image_url") if stream_type == "image" else None)
        if kind is None or not url:
            self.stats.unknown_attachments += 1
            return None
        file_name = _file_name(attachment, url)
        duration = attachment.get("duration")
        try:
            duration_ms = round(float(duration) * 1000) if duration is not None else None
        except (TypeError, ValueError):
            duration_ms = None
        return _AttachmentSpec(
            index=index,
            kind=kind,
            url=url,
            file_name=file_name,
            mime_type=attachment.get("mime_type") or mimetypes.guess_type(file_name)[0] or "",
            width=_positive_int(attachment.get("original_width")),
            height=_positive_int(attachment.get("original_height")),
            duration_ms=duration_ms,
            waveform=_waveform(attachment.get("waveform_data")),
            raw=attachment,
        )

    def _find_double_written(self, mapped) -> Message | None:
        """
        Сообщение, записанное в нашу БД параллельно со Stream без stream_id. Двойная запись бывает
        только у системных сообщений и у приветствия, поэтому только они и связываются: два
        одинаковых обычных сообщения (например, «Да» из старого и из нового приложения) — разные.

        Текст сравнивается и как есть, и после strip(): в нашу БД приветствие пишется обрезанным,
        а в Stream — как ввёл специалист.
        """
        texts = {mapped.text, mapped.text.strip()}
        window = Q(
            created_at__gte=mapped.created_at - DOUBLE_WRITE_WINDOW,
            created_at__lte=mapped.created_at + DOUBLE_WRITE_WINDOW,
        )
        if mapped.type == Message.Type.SYSTEM:
            return (
                Message.objects.filter(
                    window,
                    chat=self.chat,
                    sender__isnull=True,
                    stream_id__isnull=True,
                    type=Message.Type.SYSTEM,
                    custom_type=mapped.custom_type,
                    text__in=texts,
                )
                .order_by("created_at", "id")
                .first()
            )
        if mapped.type != Message.Type.REGULAR or mapped.sender_id != self.chat.specialist_id:
            return None
        # приветствие — первое обычное сообщение чата, от специалиста
        first = (
            Message.objects.filter(chat=self.chat, type=Message.Type.REGULAR)
            .order_by("created_at", "id")
            .first()
        )
        if (
            first is not None
            and first.stream_id is None
            and first.sender_id == self.chat.specialist_id
            and first.text in texts
            and abs(first.created_at - mapped.created_at) <= DOUBLE_WRITE_WINDOW
        ):
            return first
        return None

    def _import_message(self, raw, existing) -> None:
        mapped = self._map(raw)
        if mapped is None:
            self.stats.messages_skipped += 1
            return

        linked = False
        if existing is None:
            existing = self._find_double_written(mapped)
            linked = existing is not None

        if existing is not None:
            message = existing
            changed = self._apply_changes(message, mapped)
            if linked:
                message.stream_id = mapped.stream_id
                changed.append("stream_id")
                self.stats.messages_linked += 1
            elif changed:
                self.stats.messages_updated += 1
            else:
                self.stats.messages_skipped += 1
            if changed and not self.dry_run:
                message.save(update_fields=changed)
        else:
            self.stats.messages_created += 1
            message = None
            if not self.dry_run:
                message = Message.objects.create(
                    chat=self.chat,
                    sender_id=mapped.sender_id,
                    type=mapped.type,
                    custom_type=mapped.custom_type,
                    text=mapped.text,
                    extra_data=mapped.extra_data,
                    stream_id=mapped.stream_id,
                    created_at=mapped.created_at,
                    edited_at=mapped.edited_at,
                    deleted_at=mapped.deleted_at,
                )

        if message is not None and mapped.reply_to_stream_id and message.reply_to_id is None:
            self.reply_links.append((message.pk, mapped.reply_to_stream_id))
        self._import_attachments(message, mapped)

    @staticmethod
    def _apply_changes(message, mapped) -> list[str]:
        """Удаление и правки из Stream; более поздняя правка в нашем мессенджере не перетирается."""
        changed = []
        if mapped.deleted_at and message.deleted_at is None:
            message.deleted_at = mapped.deleted_at
            changed.append("deleted_at")
        if mapped.edited_at and (message.edited_at is None or mapped.edited_at > message.edited_at):
            message.text = mapped.text
            message.edited_at = mapped.edited_at
            changed += ["text", "edited_at"]
        return changed

    # --- вложения ---

    def _attachment_id(self, mapped, spec) -> uuid.UUID:
        return uuid.uuid5(ATTACHMENT_NAMESPACE, f"{mapped.stream_id}:{spec.index}")

    def _import_attachments(self, message, mapped) -> None:
        for spec in mapped.attachments:
            attachment_id = self._attachment_id(mapped, spec)
            if Attachment.objects.filter(pk=attachment_id).exists():
                if message is not None:
                    self._mark_failed_attachment(message, spec, failed=False)
                continue
            if self.dry_run:
                self.stats.attachments += 1
                continue
            try:
                self._store_attachment(message, mapped, spec, attachment_id)
            except Exception as exc:
                logger.exception(
                    "Failed to import attachment %s#%s of %s", mapped.stream_id, spec.index, self.chat.channel_id
                )
                self.stats.errors.append(
                    f"{self.chat.channel_id}: attachment {mapped.stream_id}#{spec.index}: {exc}"
                )
                self._mark_failed_attachment(message, spec, failed=True)
            else:
                self.stats.attachments += 1
                self._mark_failed_attachment(message, spec, failed=False)

    @staticmethod
    def _mark_failed_attachment(message, spec, *, failed: bool) -> None:
        """
        След несостоявшегося скачивания: исходное вложение Stream (+ `import_failed_index`) в
        `extra_data["stream_attachments"]`, чтобы файл не пропал бесследно. Убирается, когда
        повторный запуск импорта скачал вложение.
        """
        entries = list(message.extra_data.get("stream_attachments") or [])
        kept = [
            entry for entry in entries
            if not (isinstance(entry, dict) and entry.get("import_failed_index") == spec.index)
        ]
        if failed:
            kept.append({**spec.raw, "import_failed_index": spec.index})
        if kept == entries:
            return
        if kept:
            message.extra_data["stream_attachments"] = kept
        else:
            message.extra_data.pop("stream_attachments", None)
        message.save(update_fields=["extra_data"])

    def _store_attachment(self, message, mapped, spec, attachment_id) -> None:
        object_key = f"chats/{self.chat.pk}/{attachment_id}/{storage.safe_file_name(spec.file_name)}"
        response = _download(spec.url)
        try:
            response.raise_for_status()
            content_type = (
                spec.mime_type
                or (response.headers or {}).get("Content-Type", "").split(";")[0].strip()
                or "application/octet-stream"
            )
            if hasattr(response.raw, "decode_content"):
                response.raw.decode_content = True
            reader = _CountingReader(response.raw)
            storage.put_stream(object_key, reader, content_type)
        finally:
            response.close()

        Attachment.objects.create(
            id=attachment_id,
            uploader_id=mapped.sender_id or self.chat.specialist_id,
            chat=self.chat,
            message=message,
            kind=spec.kind,
            object_key=object_key,
            file_name=spec.file_name,
            mime_type=content_type,
            size=reader.count,
            width=spec.width,
            height=spec.height,
            duration_ms=spec.duration_ms,
            waveform=spec.waveform,
            position=spec.index,
            status=Attachment.Status.READY,
        )

    # --- после всех страниц ---

    def _link_replies(self) -> None:
        """Второй проход: quoted_message_id/parent_id -> reply_to (цель может быть на любой странице)."""
        if not self.reply_links:
            return
        targets = dict(
            Message.objects.filter(
                chat=self.chat, stream_id__in={stream_id for _, stream_id in self.reply_links}
            ).values_list("stream_id", "pk")
        )
        for message_pk, reply_stream_id in self.reply_links:
            target_pk = targets.get(reply_stream_id)
            if target_pk is not None and target_pk != message_pk:
                Message.objects.filter(pk=message_pk, reply_to__isnull=True).update(reply_to_id=target_pk)
                continue
            # исходное сообщение удалено из Stream насовсем — сохраняем ссылку для истории
            message = Message.objects.get(pk=message_pk)
            if message.extra_data.get("stream_reply_to_id") != reply_stream_id:
                message.extra_data["stream_reply_to_id"] = reply_stream_id
                message.save(update_fields=["extra_data"])

    def _read_target(self, entry) -> Message | None:
        stream_id = entry.get("last_read_message_id")
        if stream_id:
            message = Message.objects.filter(chat=self.chat, stream_id=stream_id).first()
            if message is not None:
                return message
        last_read = _parse_ts(entry.get("last_read"))
        if last_read is None:
            return None
        return (
            Message.objects.filter(chat=self.chat, created_at__lte=last_read)
            .order_by("-created_at", "-id")
            .first()
        )

    def _apply_read_state(self, read_entries) -> None:
        """
        `channel.read` -> last_read_message_id (только вперёд) и пересчёт unread_count
        по тому же правилу, что и `read_state.mark_read` (`read_state.unread_count`).

        Если пользователь уже менял позицию в новом приложении (`read_changed_at`: read/unread),
        позиция из Stream не применяется — только пересчитывается unread_count.
        """
        reads = {}
        for entry in read_entries:
            user_id = str((entry.get("user") or {}).get("id") or "")
            if user_id.isdigit():
                reads[int(user_id)] = entry

        with transaction.atomic():
            members = ChatMember.objects.select_for_update().filter(chat=self.chat)
            for member in members:
                current = None
                if member.last_read_message_id is not None:
                    current = Message.objects.filter(chat=self.chat, pk=member.last_read_message_id).first()
                entry = reads.get(member.user_id) if member.read_changed_at is None else None
                target = self._read_target(entry) if entry else None
                if target is not None and (current is None or _position(target) > _position(current)):
                    current = target

                unread = unread_count(self.chat, member.user_id, current)
                last_read_id = current.pk if current else member.last_read_message_id
                if (member.last_read_message_id, member.unread_count) != (last_read_id, unread):
                    member.last_read_message_id = last_read_id
                    member.unread_count = unread
                    member.save(update_fields=["last_read_message_id", "unread_count", "updated_at"])

    def _apply_pinned_state(self, member_entries) -> None:
        """
        `channel.members[].pinned_at` -> ChatMember.pinned_at, только если у нас чат не закреплён и
        пользователь ни разу не закреплял/откреплял его в новом приложении (`pin_changed_at` пуст):
        повторный импорт не возвращает закрепление, снятое в новом приложении. Идемпотентно.
        """
        for entry in member_entries:
            user_id = str(entry.get("user_id") or (entry.get("user") or {}).get("id") or "")
            try:
                pinned_at = _parse_ts(entry.get("pinned_at"))
            except ValueError as exc:
                self.stats.errors.append(f"{self.chat.channel_id}: pinned_at of {user_id}: {exc}")
                continue
            if not user_id.isdigit() or pinned_at is None:
                continue
            ChatMember.objects.filter(
                chat=self.chat, user_id=int(user_id), pinned_at__isnull=True, pin_changed_at__isnull=True
            ).update(pinned_at=pinned_at)

    def _update_last_message(self) -> None:
        last = Message.objects.filter(chat=self.chat).order_by("-created_at", "-id").first()
        if last is None:
            return
        # как в messages._apply_new_message: параллельно пришедшее более новое сообщение не перетираем
        Chat.objects.filter(pk=self.chat.pk).filter(
            Q(last_message_at__isnull=True) | Q(last_message_at__lte=last.created_at)
        ).update(last_message=last, last_message_at=last.created_at)


# --- публичный API ---

def import_channel(chat, *, since: datetime | None = None, dry_run: bool = False) -> ImportStats:
    """Импорт одного канала. Ошибки отдельных сообщений/вложений — в `errors`; ошибка канала — исключение."""
    stats = ImportStats(channels=1)
    _ChannelImporter(chat, stats, dry_run).run(since)
    return stats


def import_all(
    *, channel_id: str | None = None, since: datetime | None = None, dry_run: bool = False, on_channel=None
) -> ImportStats:
    """
    Импорт всех чатов (или одного по `channel_id`) по возрастанию id.

    Ошибка канала записывается в `errors`, импорт продолжается со следующего.
    `on_channel(chat, channel_stats)` — необязательный колбэк прогресса.
    """
    stats = ImportStats()
    chats = Chat.objects.exclude(channel_id__isnull=True).exclude(channel_id="").order_by("pk")
    if channel_id:
        chats = chats.filter(channel_id=channel_id)
        if not chats.exists():
            stats.errors.append(f"{channel_id}: чат не найден")
            return stats

    for chat in chats.iterator():
        channel_stats = ImportStats(channels=1)
        try:
            _ChannelImporter(chat, channel_stats, dry_run).run(since)
        except Exception as exc:
            logger.exception("Failed to import channel %s", chat.channel_id)
            channel_stats.errors.append(f"{chat.channel_id}: {exc}")
        logger.info("Imported %s: %s", chat.channel_id, channel_stats.summary())
        if on_channel is not None:
            on_channel(chat, channel_stats)
        stats.merge(channel_stats)
    return stats
