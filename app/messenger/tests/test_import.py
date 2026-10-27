import copy
import io
import json
from datetime import datetime, timedelta, timezone as dt_timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from stream_chat.base.exceptions import StreamAPIException

from account.models import ROLE_CLIENT
from chat_access.models import Chat
from chat_access.services.chat_commands import create_or_get_chat
from messenger.models import Attachment, Call, ChatMember, Message
from messenger.services import getstream_import
from messenger.tests.base import MessengerTestCase

User = get_user_model()

FIXTURE = Path(__file__).parent / "fixtures" / "stream_channel.json"
MODULE = "messenger.services.getstream_import"

FILES = {
    "photo.jpg": b"JPEGDATA1234",
    "report.pdf": b"%PDF-1.4\n",
    "voice.aac": b"VOICE",
    "note.m4a": b"VOICENOTE",
}


def load_fixture(chat):
    raw = FIXTURE.read_text(encoding="utf-8")
    raw = (
        raw.replace("__CLIENT__", str(chat.client_id))
        .replace("__SPECIALIST__", str(chat.specialist_id))
        .replace("__CHANNEL__", chat.channel_id)
    )
    return json.loads(raw)


def _ts(message):
    return parse_datetime(message["created_at"])


def _paginate(messages, options):
    """Пагинация сообщений как у Stream: фильтр по created_at, от старых к новым, первые `limit`."""
    items = sorted(messages, key=_ts)
    if "created_at_after_or_equal" in options:
        bound = parse_datetime(options["created_at_after_or_equal"])
        items = [m for m in items if _ts(m) >= bound]
    if "created_at_after" in options:
        bound = parse_datetime(options["created_at_after"])
        items = [m for m in items if _ts(m) > bound]
    return copy.deepcopy(items[: options.get("limit", 100)])


class FakeStreamChannel:
    """Канал stream_chat.Channel поверх фикстуры: query(messages=...) и get_replies(parent_id, ...)."""

    def __init__(self, data):
        self.data = data
        self.query_calls = []
        self.replies_calls = []
        self.query_errors = []

    def query(self, **options):
        self.query_calls.append(copy.deepcopy(options))
        if self.query_errors:
            raise self.query_errors.pop(0)
        response = copy.deepcopy(self.data["query_response"])
        response["messages"] = _paginate(self.data["query_response"]["messages"], options.get("messages", {}))
        return response

    def get_replies(self, parent_id, **options):
        self.replies_calls.append((parent_id, copy.deepcopy(options)))
        messages = self.data["replies_responses"].get(parent_id, {"messages": []})["messages"]
        return {"messages": _paginate(messages, options), "duration": "1ms"}


class FakeResponse:
    def __init__(self, url):
        name = url.split("?")[0].rsplit("/", 1)[-1]
        self.content = FILES.get(name)
        self.status_code = 200 if self.content is not None else 404
        self.headers = {"Content-Type": "application/octet-stream"}
        self.raw = io.BytesIO(self.content or b"")
        self.closed = False

    def raise_for_status(self):
        if self.status_code >= 400:
            import requests

            raise requests.HTTPError(f"{self.status_code} for url")

    def close(self):
        self.closed = True


class ImportTestCase(MessengerTestCase):
    def setUp(self):
        super().setUp()
        self.fixture = load_fixture(self.chat)
        self.channels = {self.chat.channel_id: FakeStreamChannel(self.fixture)}

        self.stream_client = MagicMock()
        self.stream_client.channel.side_effect = self._channel
        for target, value in (
            ("common.stream_client.chat_client", self.stream_client),
            (f"{MODULE}.PAGE_SIZE", 2),
        ):
            patcher = patch(target, value)
            patcher.start()
            self.addCleanup(patcher.stop)

        self.stored = {}
        storage_patcher = patch("messenger.clients.storage.put_stream", side_effect=self._put_stream)
        self.put_stream_mock = storage_patcher.start()
        self.addCleanup(storage_patcher.stop)

        get_patcher = patch(f"{MODULE}.requests.get", side_effect=lambda url, **kw: FakeResponse(url))
        self.requests_get_mock = get_patcher.start()
        self.addCleanup(get_patcher.stop)

        sleep_patcher = patch(f"{MODULE}.time.sleep")
        self.sleep_mock = sleep_patcher.start()
        self.addCleanup(sleep_patcher.stop)

    def _channel(self, channel_type, channel_id, *args, **kwargs):
        channel = self.channels[channel_id]
        if isinstance(channel, Exception):
            raise channel
        return channel

    def _put_stream(self, key, fileobj, content_type):
        self.stored[key] = (fileobj.read(), content_type)

    def run_import(self, **kwargs):
        kwargs.setdefault("since", None)
        kwargs.setdefault("dry_run", False)
        return getstream_import.import_channel(self.chat, **kwargs)

    def msg(self, stream_id):
        return Message.objects.get(stream_id=stream_id)


class ImportMappingTestCase(ImportTestCase):
    def test_import_maps_regular_system_deleted_and_reply(self):
        stats = self.run_import()

        self.assertEqual(stats.errors, [])
        self.assertEqual(stats.channels, 1)
        self.assertEqual(stats.messages_created, 12)
        self.assertEqual(Message.objects.filter(chat=self.chat).count(), 12)

        greeting = self.msg("msg-greeting")
        self.assertEqual(greeting.type, Message.Type.REGULAR)
        self.assertEqual(greeting.sender_id, self.specialist.pk)
        self.assertEqual(greeting.text, "Здравствуйте! Чем могу помочь?")
        self.assertEqual(greeting.created_at, datetime(2025, 3, 1, 9, 0, 0, 100000, tzinfo=dt_timezone.utc))
        self.assertIsNone(greeting.edited_at)
        self.assertIsNone(greeting.deleted_at)

        system = self.msg("msg-sys-tariff")
        self.assertEqual(system.type, Message.Type.SYSTEM)
        self.assertIsNone(system.sender_id)
        self.assertEqual(system.custom_type, "tariffActivated")
        self.assertEqual(system.text, "Тариф активирован.")
        self.assertEqual(
            system.extra_data,
            {"customType": "tariffActivated", "clientName": "Иван Клиентов", "specialistName": "Анна Врачева"},
        )

        deleted = self.msg("msg-deleted")
        self.assertEqual(deleted.type, Message.Type.REGULAR)
        self.assertEqual(deleted.deleted_at, datetime(2025, 3, 1, 9, 5, tzinfo=dt_timezone.utc))

        edited = self.msg("msg-edited")
        self.assertEqual(edited.text, "Исправленный текст")
        self.assertEqual(edited.edited_at, datetime(2025, 3, 1, 9, 10, tzinfo=dt_timezone.utc))

        # quoted_message_id -> reply_to
        self.assertEqual(self.msg("msg-quote").reply_to_id, self.msg("msg-photo").pk)
        # ответ в треде (parent_id) -> reply_to, сообщение попадает в ленту
        thread_reply = self.msg("msg-thread-reply")
        self.assertEqual(thread_reply.reply_to_id, greeting.pk)
        self.assertEqual(thread_reply.sender_id, self.client_user.pk)
        self.assertEqual(thread_reply.type, Message.Type.REGULAR)

    def test_same_timestamp_messages_on_page_boundary_are_not_lost(self):
        self.run_import()

        a, b = self.msg("msg-same-ts-a"), self.msg("msg-same-ts-b")
        self.assertEqual(a.created_at, b.created_at)
        self.assertLess(a.pk, b.pk)

    def test_pages_from_oldest_to_newest(self):
        self.run_import()

        calls = self.channels[self.chat.channel_id].query_calls
        self.assertGreater(len(calls), 1)
        first = calls[0]["messages"]
        self.assertEqual(first["limit"], 2)
        self.assertEqual(parse_datetime(first["created_at_after_or_equal"]).year, 1970)
        # следующая страница начинается со времени последнего сообщения предыдущей
        self.assertEqual(calls[1]["messages"]["created_at_after_or_equal"], "2025-03-01T09:01:00.000000Z")

    def test_unknown_stream_user_kept_in_extra_data(self):
        stats = self.run_import()

        message = self.msg("msg-unknown-user")
        self.assertIsNone(message.sender_id)
        self.assertEqual(message.type, Message.Type.REGULAR)
        self.assertEqual(message.extra_data["stream_user_id"], "999999")
        self.assertEqual(stats.unknown_users, 1)

    def test_non_uploadable_attachments_kept_link_previews_skipped(self):
        stats = self.run_import()

        giphy = self.msg("msg-giphy")
        self.assertEqual(giphy.text, "/giphy hello")
        self.assertEqual([a["type"] for a in giphy.extra_data["stream_attachments"]], ["giphy"])
        self.assertEqual(stats.unknown_attachments, 1)
        self.assertFalse(giphy.attachments.exists())

        quote = self.msg("msg-quote")
        self.assertEqual(quote.text, "Посмотрел, всё хорошо. Подробнее https://example.com/info")
        self.assertNotIn("stream_attachments", quote.extra_data)
        self.assertEqual(stats.link_previews, 1)

    def test_last_message_updated(self):
        self.run_import()

        self.chat.refresh_from_db()
        self.assertEqual(self.chat.last_message_id, self.msg("msg-same-ts-b").pk)
        self.assertEqual(self.chat.last_message_at, datetime(2025, 3, 1, 9, 11, tzinfo=dt_timezone.utc))

    def test_import_does_not_publish_events_or_pushes(self):
        with patch("messenger.tasks.send_message_push.delay") as push_mock:
            with self.captureOnCommitCallbacks(execute=True):
                self.run_import()

        self.broadcast_mock.assert_not_called()
        push_mock.assert_not_called()

    def test_since_limits_query(self):
        since = datetime(2025, 3, 1, 9, 6, tzinfo=dt_timezone.utc)
        stats = self.run_import(since=since)

        first = self.channels[self.chat.channel_id].query_calls[0]["messages"]
        self.assertEqual(parse_datetime(first["created_at_after_or_equal"]), since)
        self.assertFalse(Message.objects.filter(stream_id="msg-photo").exists())
        self.assertTrue(Message.objects.filter(stream_id="msg-voice").exists())
        self.assertEqual(stats.messages_created, 6)

    def test_double_written_message_is_linked_not_duplicated(self):
        # переходный период: системное сообщение записано и в Stream, и в нашу БД
        existing = Message.objects.create(
            chat=self.chat,
            sender=None,
            type=Message.Type.SYSTEM,
            custom_type="tariffActivated",
            text="Тариф активирован.",
            created_at=datetime(2025, 3, 1, 9, 2, 1, tzinfo=dt_timezone.utc),
        )
        greeting = Message.objects.create(
            chat=self.chat,
            sender=self.specialist,
            text="Здравствуйте! Чем могу помочь?",
            created_at=datetime(2025, 3, 1, 9, 0, 0, 50000, tzinfo=dt_timezone.utc),
        )

        stats = self.run_import()

        existing.refresh_from_db()
        greeting.refresh_from_db()
        self.assertEqual(existing.stream_id, "msg-sys-tariff")
        self.assertEqual(greeting.stream_id, "msg-greeting")
        self.assertEqual(Message.objects.filter(chat=self.chat).count(), 12)
        self.assertEqual(stats.messages_linked, 2)
        self.assertEqual(stats.messages_created, 10)

    def test_identical_regular_messages_within_window_are_not_merged(self):
        # «Да» есть только в Stream (старое приложение), и ещё одно «Да» — в новом приложении
        # через 30 с: это два разных сообщения, а не двойная запись
        stream_messages = self.fixture["query_response"]["messages"]
        for stream_id, user_id in (("msg-da-client", self.client_user.pk), ("msg-da-specialist", self.specialist.pk)):
            stream_messages.append({
                "id": stream_id,
                "type": "regular",
                "user": {"id": str(user_id)},
                "text": "Да",
                "created_at": "2025-03-01T09:12:00.000000Z",
                "attachments": [],
            })
        native = [
            Message.objects.create(
                chat=self.chat, sender=sender, text="Да",
                created_at=datetime(2025, 3, 1, 9, 12, 30, tzinfo=dt_timezone.utc),
            )
            for sender in (self.client_user, self.specialist)
        ]

        stats = self.run_import()

        self.assertEqual(stats.messages_linked, 0)
        for message in native:
            message.refresh_from_db()
            self.assertIsNone(message.stream_id)
        self.assertEqual(Message.objects.filter(chat=self.chat, text="Да").count(), 4)
        self.assertTrue(Message.objects.filter(stream_id="msg-da-client").exists())
        self.assertTrue(Message.objects.filter(stream_id="msg-da-specialist").exists())

    def test_padded_greeting_in_stream_is_linked(self):
        # в Stream приветствие уходит как есть, в нашу БД — после strip()
        greeting_raw = next(m for m in self.fixture["query_response"]["messages"] if m["id"] == "msg-greeting")
        greeting_raw["text"] = "  Здравствуйте! Чем могу помочь?\n"
        greeting = Message.objects.create(
            chat=self.chat,
            sender=self.specialist,
            text="Здравствуйте! Чем могу помочь?",
            created_at=datetime(2025, 3, 1, 9, 0, 0, 50000, tzinfo=dt_timezone.utc),
        )

        stats = self.run_import()

        greeting.refresh_from_db()
        self.assertEqual(greeting.stream_id, "msg-greeting")
        self.assertEqual(greeting.text, "Здравствуйте! Чем могу помочь?")
        self.assertEqual(stats.messages_linked, 1)
        self.assertEqual(Message.objects.filter(chat=self.chat).count(), 12)

    def test_last_message_never_moves_backwards(self):
        # параллельно пришло более новое сообщение: last_message_at уже впереди всего импортируемого
        newer = Message.objects.create(chat=self.chat, sender=self.specialist, text="новое", created_at=timezone.now())
        ahead = timezone.now() + timedelta(hours=1)
        Chat.objects.filter(pk=self.chat.pk).update(last_message=newer, last_message_at=ahead)

        self.run_import()

        self.chat.refresh_from_db()
        self.assertEqual(self.chat.last_message_id, newer.pk)
        self.assertEqual(self.chat.last_message_at, ahead)


class ImportAttachmentsTestCase(ImportTestCase):
    def test_import_downloads_attachments_to_storage(self):
        stats = self.run_import()

        self.assertEqual(stats.errors, [])
        self.assertEqual(stats.attachments, 3)
        self.assertEqual(len(self.stored), 3)

        image = self.msg("msg-photo").attachments.get()
        self.assertEqual(image.kind, Attachment.Kind.IMAGE)
        self.assertEqual(image.status, Attachment.Status.READY)
        self.assertEqual(image.chat_id, self.chat.pk)
        self.assertEqual(image.uploader_id, self.client_user.pk)
        self.assertEqual(image.file_name, "photo.jpg")
        self.assertEqual(image.mime_type, "image/jpeg")
        self.assertEqual(image.size, len(FILES["photo.jpg"]))
        self.assertEqual((image.width, image.height), (800, 600))
        self.assertTrue(image.object_key.startswith(f"chats/{self.chat.pk}/{image.pk}/"))
        self.assertTrue(image.object_key.endswith("/photo.jpg"))
        self.assertEqual(self.stored[image.object_key], (FILES["photo.jpg"], "image/jpeg"))

        document = self.msg("msg-quote").attachments.get()
        self.assertEqual(document.kind, Attachment.Kind.FILE)
        self.assertEqual(document.file_name, "Анализ крови.pdf")
        self.assertEqual(document.mime_type, "application/pdf")
        self.assertEqual(document.uploader_id, self.specialist.pk)
        self.assertEqual(self.stored[document.object_key][0], FILES["report.pdf"])

        voice = self.msg("msg-voice").attachments.get()
        self.assertEqual(voice.kind, Attachment.Kind.VOICE)
        self.assertEqual(voice.duration_ms, 3500)
        self.assertEqual(voice.waveform, [10, 50, 100])
        self.assertEqual(voice.mime_type, "audio/aac")
        self.assertEqual(voice.size, len(FILES["voice.aac"]))

        # потоковое скачивание
        for call in self.requests_get_mock.call_args_list:
            self.assertTrue(call.kwargs.get("stream"))
            self.assertIn("timeout", call.kwargs)

    def test_attachment_position_follows_stream_order(self):
        messages = {m["id"]: m for m in self.fixture["query_response"]["messages"]}
        document = dict(next(a for a in messages["msg-quote"]["attachments"] if a.get("type") == "file"))
        messages["msg-photo"]["attachments"].insert(0, document)  # [файл, фото]

        self.run_import()

        photo = self.msg("msg-photo")
        self.assertEqual(
            list(photo.attachments.order_by("position").values_list("kind", "position")),
            [(Attachment.Kind.FILE, 0), (Attachment.Kind.IMAGE, 1)],
        )
        self.auth(self.client_user)
        with patch("messenger.clients.storage.presigned_get", return_value="https://files/x"):
            results = self.client.get(f"/api/chats/{self.chat.channel_id}/messages/?limit=100").json()["results"]
        api_photo = next(m for m in results if m["id"] == photo.pk)
        self.assertEqual([a["kind"] for a in api_photo["attachments"]], ["file", "image"])

    def test_attachment_url_appears_in_api(self):
        self.run_import()
        self.auth(self.client_user)
        with patch("messenger.clients.storage.presigned_get", return_value="https://files/x"):
            response = self.client.get(f"/api/chats/{self.chat.channel_id}/messages/?limit=100")

        self.assertEqual(response.status_code, 200)
        photo = next(m for m in response.json()["results"] if m["text"] == "Вот снимок")
        self.assertEqual(photo["attachments"][0]["url"], "https://files/x")

    def test_failed_download_is_reported_and_retried_next_run(self):
        missing = FILES.pop("voice.aac")
        self.addCleanup(FILES.__setitem__, "voice.aac", missing)

        stats = self.run_import()

        self.assertEqual(len(stats.errors), 1)
        self.assertIn("msg-voice", stats.errors[0])
        voice_message = self.msg("msg-voice")
        self.assertFalse(voice_message.attachments.exists())
        self.assertEqual(stats.attachments, 2)
        # след в сообщении: исходное вложение Stream с пометкой о сбое скачивания
        failed = voice_message.extra_data["stream_attachments"]
        self.assertEqual(len(failed), 1)
        self.assertEqual(failed[0]["type"], "voiceRecording")
        self.assertIn("/voice.aac", failed[0]["asset_url"])
        self.assertEqual(failed[0]["import_failed_index"], 0)

        # повторный сбой не дублирует запись
        self.run_import()
        self.assertEqual(len(self.msg("msg-voice").extra_data["stream_attachments"]), 1)

        FILES["voice.aac"] = missing
        second = self.run_import()

        self.assertEqual(second.errors, [])
        self.assertEqual(second.attachments, 1)
        self.assertEqual(voice_message.attachments.get().kind, Attachment.Kind.VOICE)
        voice_message.refresh_from_db()
        self.assertNotIn("stream_attachments", voice_message.extra_data)

    def test_dry_run_writes_nothing(self):
        stats = self.run_import(dry_run=True)

        self.assertEqual(stats.messages_created, 12)
        self.assertEqual(stats.attachments, 3)
        self.assertFalse(Message.objects.filter(chat=self.chat).exists())
        self.assertFalse(Attachment.objects.exists())
        self.requests_get_mock.assert_not_called()
        self.put_stream_mock.assert_not_called()
        self.assertIsNone(ChatMember.objects.get(chat=self.chat, user=self.client_user).last_read_message_id)


class ImportReadStateTestCase(ImportTestCase):
    def test_import_sets_read_state_and_unread(self):
        self.run_import()

        client_member = ChatMember.objects.get(chat=self.chat, user=self.client_user)
        self.assertEqual(client_member.last_read_message_id, self.msg("msg-quote").pk)
        # после msg-quote от специалиста только msg-edited
        self.assertEqual(client_member.unread_count, 1)

        specialist_member = ChatMember.objects.get(chat=self.chat, user=self.specialist)
        self.assertEqual(specialist_member.last_read_message_id, self.msg("msg-same-ts-b").pk)
        self.assertEqual(specialist_member.unread_count, 0)

    def test_read_state_by_time_when_no_last_read_message_id(self):
        for read in self.fixture["query_response"]["read"]:
            read.pop("last_read_message_id")
        self.fixture["query_response"]["read"][0]["last_read"] = "2025-03-01T09:08:30.000000Z"

        self.run_import()

        client_member = ChatMember.objects.get(chat=self.chat, user=self.client_user)
        self.assertEqual(client_member.last_read_message_id, self.msg("msg-giphy").pk)
        self.assertEqual(client_member.unread_count, 1)

    def test_no_read_entry_means_everything_from_companion_unread(self):
        self.fixture["query_response"]["read"] = []

        self.run_import()

        client_member = ChatMember.objects.get(chat=self.chat, user=self.client_user)
        self.assertIsNone(client_member.last_read_message_id)
        # greeting, msg-quote, msg-edited от специалиста
        self.assertEqual(client_member.unread_count, 3)

    def test_unread_counts_only_regular_messages_like_mark_read(self):
        self.fixture["query_response"]["read"] = []
        call = Call.objects.create(
            chat=self.chat, caller=self.specialist, callee=self.client_user, room_name="call_x",
            status=Call.Status.MISSED,
        )
        Message.objects.create(chat=self.chat, sender=self.specialist, type=Message.Type.CALL, call=call)

        self.run_import()

        client_member = ChatMember.objects.get(chat=self.chat, user=self.client_user)
        # greeting, msg-quote, msg-edited; звонковое сообщение непрочитанным не считается
        self.assertEqual(client_member.unread_count, 3)

    def test_read_state_never_moves_backwards(self):
        newer = Message.objects.create(
            chat=self.chat, sender=self.specialist, text="уже в новом приложении", created_at=timezone.now()
        )
        ChatMember.objects.filter(chat=self.chat, user=self.client_user).update(
            last_read_message_id=newer.pk, unread_count=0
        )

        self.run_import()

        client_member = ChatMember.objects.get(chat=self.chat, user=self.client_user)
        self.assertEqual(client_member.last_read_message_id, newer.pk)
        self.assertEqual(client_member.unread_count, 0)
        self.chat.refresh_from_db()
        self.assertEqual(self.chat.last_message_id, newer.pk)


class ImportPinnedStateTestCase(ImportTestCase):
    def member(self, user):
        return ChatMember.objects.get(chat=self.chat, user=user)

    def pin_in_stream(self, user, value):
        for member in self.fixture["query_response"]["members"]:
            if member["user_id"] == str(user.pk):
                member["pinned_at"] = value

    def test_import_copies_member_pinned_at(self):
        self.pin_in_stream(self.client_user, "2025-03-02T10:00:00.000000Z")

        self.run_import()

        self.assertEqual(
            self.member(self.client_user).pinned_at, datetime(2025, 3, 2, 10, 0, tzinfo=dt_timezone.utc)
        )
        self.assertIsNone(self.member(self.specialist).pinned_at)

    def test_import_does_not_overwrite_existing_pin_and_is_idempotent(self):
        ours = timezone.now()
        ChatMember.objects.filter(chat=self.chat, user=self.client_user).update(pinned_at=ours)
        self.pin_in_stream(self.client_user, "2025-03-02T10:00:00.000000Z")
        self.pin_in_stream(self.specialist, "2025-03-03T10:00:00.000000Z")

        self.run_import()
        self.run_import()

        self.assertEqual(self.member(self.client_user).pinned_at, ours)
        self.assertEqual(
            self.member(self.specialist).pinned_at, datetime(2025, 3, 3, 10, 0, tzinfo=dt_timezone.utc)
        )

    def test_unpinned_in_stream_keeps_ours_and_dry_run_writes_nothing(self):
        self.pin_in_stream(self.client_user, None)
        self.run_import()
        self.assertIsNone(self.member(self.client_user).pinned_at)

        self.pin_in_stream(self.client_user, "2025-03-02T10:00:00.000000Z")
        self.run_import(dry_run=True)
        self.assertIsNone(self.member(self.client_user).pinned_at)


class ImportKeepsNewAppStateTestCase(ImportTestCase):
    """Повторный импорт (окно после переключения) не перетирает то, что пользователь сделал в новом приложении."""

    def member(self, user):
        return ChatMember.objects.get(chat=self.chat, user=user)

    def api_post(self, user, url, payload):
        self.auth(user)
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(url, payload, format="json")
        self.assertEqual(response.status_code, 200, response.content)
        return response.json()

    def test_unpinned_in_new_app_stays_unpinned_after_reimport(self):
        for member in self.fixture["query_response"]["members"]:
            if member["user_id"] == str(self.client_user.pk):
                member["pinned_at"] = "2025-03-02T10:00:00.000000Z"
        self.run_import()
        self.assertIsNotNone(self.member(self.client_user).pinned_at)

        self.api_post(self.client_user, "/api/chats/pins/remove/", {"channelId": self.chat.channel_id})
        self.run_import()

        self.assertIsNone(self.member(self.client_user).pinned_at)

    def test_marked_unread_in_new_app_stays_after_reimport(self):
        self.run_import()
        quote = self.msg("msg-quote")
        self.assertEqual(self.member(self.client_user).last_read_message_id, quote.pk)

        body = self.api_post(
            self.client_user, f"/api/chats/{self.chat.channel_id}/unread/", {"messageId": quote.pk}
        )
        self.run_import()

        member = self.member(self.client_user)
        self.assertEqual(member.last_read_message_id, body["lastReadMessageId"])
        self.assertNotEqual(member.last_read_message_id, quote.pk)
        self.assertEqual(member.unread_count, body["unreadCount"])
        # у собеседника позиция по-прежнему из Stream
        self.assertEqual(self.member(self.specialist).last_read_message_id, self.msg("msg-same-ts-b").pk)


class ImportCompletenessTestCase(ImportTestCase):
    """voicenote старых сборок, системные сообщения по isSystem / user.id=="system", счётчики потерь."""

    def add_message(self, stream_id, minute, **fields):
        raw = {
            "id": stream_id,
            "text": "",
            "type": "regular",
            "user": {"id": str(self.client_user.pk), "role": "user"},
            "attachments": [],
            "latest_reactions": [],
            "reaction_counts": {},
            "reply_count": 0,
            "created_at": f"2025-03-01T10:{minute:02d}:00.000000Z",
            "updated_at": f"2025-03-01T10:{minute:02d}:00.000000Z",
            "pinned": False,
        }
        raw.update(fields)
        self.fixture["query_response"]["messages"].append(raw)
        return raw

    def test_voicenote_imported_as_voice(self):
        self.add_message("msg-voicenote", 1, attachments=[{
            "type": "voicenote",
            "asset_url": "https://us-east.stream-io-cdn.com/1/attachments/note.m4a?Signature=Z",
            "file_size": 9,
            "duration": 2.25,
            "waveform_data": [0.2, 0.4],
        }])
        self.add_message("msg-voicenote-nested", 2, attachments=[{
            "type": "voicenote",
            "asset_url": "https://us-east.stream-io-cdn.com/1/attachments/note.m4a",
            "extraData": {"duration": 1, "waveform": [30, 60]},
        }])

        stats = self.run_import()

        self.assertEqual(stats.errors, [])
        self.assertEqual(stats.unknown_attachments, 1)  # только giphy из фикстуры
        voice = self.msg("msg-voicenote").attachments.get()
        self.assertEqual(voice.kind, Attachment.Kind.VOICE)
        self.assertEqual(voice.file_name, "note.m4a")
        self.assertEqual(voice.mime_type, "audio/mp4")
        self.assertEqual(voice.duration_ms, 2250)
        self.assertEqual(voice.waveform, [20, 40])
        self.assertEqual(voice.size, len(FILES["note.m4a"]))
        self.assertNotIn("stream_attachments", self.msg("msg-voicenote").extra_data)

        nested = self.msg("msg-voicenote-nested").attachments.get()
        self.assertEqual(nested.kind, Attachment.Kind.VOICE)
        self.assertEqual(nested.duration_ms, 1000)
        self.assertEqual(nested.waveform, [30, 60])

    def test_system_detected_by_is_system_flag_and_system_user(self):
        # старое приложение: обычное сообщение от участника с extraData.isSystem (Flutter кладёт extraData в корень)
        self.add_message("msg-sys-flag", 1, text="Срок действия тарифа истёк.", isSystem=True, customType="tariffExpired")
        # extraData, записанное бэкендом как поле `extraData`
        self.add_message(
            "msg-sys-extra", 2, text="Доступ по тарифу предоставлен.",
            user={"id": str(self.specialist.pk)},
            extraData={"isSystem": True, "customType": "tariffProvided", "client_name": "Иван"},
        )
        # отправитель system без type=system
        self.add_message("msg-sys-user", 3, text="Чат заблокирован.", user={"id": "system"}, custom_type="chatBlocked")
        # isSystem=false — обычное сообщение
        self.add_message("msg-not-sys", 4, text="Обычное", isSystem=False)

        stats = self.run_import()

        self.assertEqual(stats.errors, [])
        for stream_id, custom_type in (
            ("msg-sys-flag", "tariffExpired"),
            ("msg-sys-extra", "tariffProvided"),
            ("msg-sys-user", "chatBlocked"),
        ):
            message = self.msg(stream_id)
            self.assertEqual(message.type, Message.Type.SYSTEM, stream_id)
            self.assertIsNone(message.sender_id, stream_id)
            self.assertEqual(message.custom_type, custom_type, stream_id)
            self.assertEqual(message.extra_data["customType"], custom_type, stream_id)
            self.assertNotIn("stream_user_id", message.extra_data, stream_id)
        self.assertEqual(self.msg("msg-sys-extra").extra_data["clientName"], "Иван")

        regular = self.msg("msg-not-sys")
        self.assertEqual(regular.type, Message.Type.REGULAR)
        self.assertEqual(regular.sender_id, self.client_user.pk)
        self.assertEqual(stats.unknown_users, 1)  # только 999999 из фикстуры

    def test_imported_custom_type_validated(self):
        self.add_message("msg-sys-bad", 1, text="x", isSystem=True, customType="x" * 100)
        self.add_message("msg-sys-int", 2, text="y", isSystem=True, customType=5)
        self.add_message("msg-sys-unknown", 3, text="z", isSystem=True, customType="somethingElse")
        self.add_message("msg-sys-none", 4, text="Системное", isSystem=True)
        self.add_message("msg-sys-extra-key", 5, text="Чат заблокирован.", extra={"isSystem": True, "customType": "chatBlocked"})

        stats = self.run_import()

        self.assertEqual(stats.errors, [])
        for stream_id, raw_value in (("msg-sys-bad", "x" * 100), ("msg-sys-int", 5), ("msg-sys-unknown", "somethingElse")):
            message = self.msg(stream_id)
            self.assertEqual(message.type, Message.Type.SYSTEM, stream_id)
            self.assertEqual(message.custom_type, "", stream_id)
            self.assertNotIn("customType", message.extra_data, stream_id)
            self.assertEqual(message.extra_data["stream_custom_type"], raw_value, stream_id)
        none = self.msg("msg-sys-none")
        self.assertEqual((none.type, none.custom_type), (Message.Type.SYSTEM, ""))
        self.assertNotIn("stream_custom_type", none.extra_data)
        extra = self.msg("msg-sys-extra-key")
        self.assertEqual((extra.type, extra.custom_type), (Message.Type.SYSTEM, "chatBlocked"))

    def _add_lossy_messages(self):
        self.add_message("msg-reacted", 1, text="👍", reaction_counts={"like": 2}, latest_reactions=[{"type": "like"}])
        self.add_message("msg-reacted-groups", 2, text="ок", reaction_groups={"love": {"count": 1}})
        self.add_message("msg-pinned", 3, text="Важно", pinned=True, pinned_at="2025-03-01T10:03:30.000000Z")
        self.add_message("msg-poll", 4, text="", attachments=[{"type": "poll"}, {"type": "image"}])

    def test_loss_counters(self):
        self._add_lossy_messages()

        stats = self.run_import()

        self.assertEqual(stats.messages_with_reactions, 2)
        self.assertEqual(stats.pinned_messages, 1)
        self.assertEqual(stats.thread_replies_flattened, 1)  # msg-thread-reply из фикстуры
        self.assertEqual(stats.stream_only_attachments, {"giphy": 1, "poll": 1, "image": 1})
        self.assertEqual(stats.unknown_attachments, 3)
        self.assertIn("pinned_messages=1", stats.summary())
        self.assertIn("stream_only_attachments=giphy:1,image:1,poll:1", stats.summary())

        merged = getstream_import.ImportStats()
        merged.merge(stats)
        merged.merge(stats)
        self.assertEqual(merged.stream_only_attachments, {"giphy": 2, "poll": 2, "image": 2})
        self.assertEqual(merged.messages_with_reactions, 4)

    def test_loss_counters_in_dry_run_command_output(self):
        self._add_lossy_messages()
        out = io.StringIO()
        call_command("import_getstream", "--channel", self.chat.channel_id, "--dry-run", stdout=out)

        output = out.getvalue()
        self.assertIn("dry-run", output)
        self.assertIn("messages_with_reactions=2", output)
        self.assertIn("pinned_messages=1", output)
        self.assertIn("thread_replies_flattened=1", output)
        self.assertIn("stream_only_attachments=giphy:1,image:1,poll:1", output)
        self.assertFalse(Message.objects.exists())


class ImportIdempotencyTestCase(ImportTestCase):
    def test_import_is_idempotent(self):
        first = self.run_import()
        downloads = self.requests_get_mock.call_count
        ids = sorted(Message.objects.filter(chat=self.chat).values_list("pk", flat=True))

        second = self.run_import()

        self.assertEqual(first.messages_created, 12)
        self.assertEqual(second.messages_created, 0)
        self.assertEqual(second.messages_skipped, 12)
        self.assertEqual(second.attachments, 0)
        self.assertEqual(sorted(Message.objects.filter(chat=self.chat).values_list("pk", flat=True)), ids)
        self.assertEqual(Attachment.objects.count(), 3)
        self.assertEqual(self.requests_get_mock.call_count, downloads)
        self.assertEqual(self.put_stream_mock.call_count, 3)

    def test_rerun_updates_deleted_and_edited(self):
        self.run_import()
        for message in self.fixture["query_response"]["messages"]:
            if message["id"] == "msg-photo":
                message.update(type="deleted", deleted_at="2025-03-02T10:00:00.000000Z", text="")
            if message["id"] == "msg-edited":
                message.update(text="Ещё раз исправлено", message_text_updated_at="2025-03-02T11:00:00.000000Z")

        stats = self.run_import()

        self.assertEqual(stats.messages_updated, 2)
        self.assertEqual(stats.messages_created, 0)
        photo = self.msg("msg-photo")
        self.assertEqual(photo.deleted_at, datetime(2025, 3, 2, 10, tzinfo=dt_timezone.utc))
        self.assertEqual(photo.text, "Вот снимок")  # текст сохраняется, скрывается при выдаче
        edited = self.msg("msg-edited")
        self.assertEqual(edited.text, "Ещё раз исправлено")
        self.assertEqual(edited.edited_at, datetime(2025, 3, 2, 11, tzinfo=dt_timezone.utc))

    def test_retries_on_rate_limit(self):
        channel = self.channels[self.chat.channel_id]
        channel.query_errors = [
            StreamAPIException('{"code": 9, "message": "Too many requests"}', 429),
            StreamAPIException('{"code": 9, "message": "Too many requests"}', 429),
        ]

        stats = self.run_import()

        self.assertEqual(stats.errors, [])
        self.assertEqual(stats.messages_created, 12)
        self.assertEqual([c.args[0] for c in self.sleep_mock.call_args_list], [1, 2])

    def test_rate_limit_gives_up_after_5_attempts(self):
        channel = self.channels[self.chat.channel_id]
        channel.query_errors = [
            StreamAPIException('{"code": 9, "message": "Too many requests"}', 429) for _ in range(5)
        ]

        with self.assertRaises(StreamAPIException):
            self.run_import()
        self.assertEqual(self.sleep_mock.call_count, 4)


class ImportAllTestCase(ImportTestCase):
    def setUp(self):
        super().setUp()
        self.other_client = User.objects.create_user(username="client_2", password="pass", role=ROLE_CLIENT)
        self.other_chat = create_or_get_chat(self.other_client, self.specialist)

    def test_import_continues_after_channel_error(self):
        # первый по id чат падает, второй импортируется
        self.channels[self.chat.channel_id] = StreamAPIException('{"code": 16, "message": "Not found"}', 404)
        self.channels[self.other_chat.channel_id] = FakeStreamChannel(load_fixture(self.other_chat))

        stats = getstream_import.import_all()

        self.assertEqual(stats.channels, 2)
        self.assertEqual(len(stats.errors), 1)
        self.assertIn(self.chat.channel_id, stats.errors[0])
        self.assertFalse(Message.objects.filter(chat=self.chat).exists())
        self.assertEqual(Message.objects.filter(chat=self.other_chat).count(), 12)
        self.assertEqual(stats.messages_created, 12)

    def test_import_all_single_channel(self):
        self.channels[self.other_chat.channel_id] = FakeStreamChannel(load_fixture(self.other_chat))

        stats = getstream_import.import_all(channel_id=self.other_chat.channel_id)

        self.assertEqual(stats.channels, 1)
        self.assertFalse(Message.objects.filter(chat=self.chat).exists())
        self.assertEqual(Message.objects.filter(chat=self.other_chat).count(), 12)

    def test_unknown_channel_reported(self):
        stats = getstream_import.import_all(channel_id="chat_nope")

        self.assertEqual(stats.channels, 0)
        self.assertEqual(len(stats.errors), 1)

    def test_management_command_prints_summary(self):
        out = io.StringIO()
        call_command("import_getstream", "--channel", self.chat.channel_id, stdout=out)

        output = out.getvalue()
        self.assertIn("channels=1", output)
        self.assertIn("messages_created=12", output)
        self.assertIn("attachments=3", output)
        self.assertIn("errors=0", output)
        self.assertEqual(Message.objects.filter(chat=self.chat).count(), 12)

    def test_management_command_dry_run_and_since(self):
        out = io.StringIO()
        call_command(
            "import_getstream",
            "--channel", self.chat.channel_id,
            "--since", "2025-03-01T09:06:00Z",
            "--dry-run",
            stdout=out,
        )

        self.assertIn("messages_created=6", out.getvalue())
        self.assertIn("dry-run", out.getvalue())
        self.assertFalse(Message.objects.exists())

    def test_management_command_rejects_bad_since(self):
        from django.core.management.base import CommandError

        with self.assertRaises(CommandError):
            call_command("import_getstream", "--since", "вчера", stdout=io.StringIO())
