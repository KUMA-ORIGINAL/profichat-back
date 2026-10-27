from datetime import timedelta
from unittest.mock import MagicMock, patch

import requests
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.db import connection
from django.test import override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from account.models import ROLE_SPECIALIST
from chat_access.models import BlockedChat
from chat_access.services.chat_commands import create_or_get_chat
from messenger.clients import centrifugo
from messenger.clients.centrifugo import CentrifugoError
from messenger.models import Message, UserPresence
from messenger.services import events, presence
from messenger.tests.base import MessengerTestCase

User = get_user_model()

# Оригинальная функция: MessengerTestCase подменяет её на мок в setUp
REAL_PRESENCE_STATS_BATCH = centrifugo.presence_stats_batch
API_URL = "http://centrifugo.test/api"


def http_response(status=200, body=None):
    response = MagicMock(status_code=status, text=str(body))
    response.json.return_value = body
    return response


@override_settings(CENTRIFUGO_API_URL=API_URL, CENTRIFUGO_API_KEY="key")
class PresenceStatsBatchClientTests(MessengerTestCase):
    """Один HTTP-запрос `batch` с `presence_stats` на каждый канал."""

    def test_single_batch_request_and_reply_parsing(self):
        body = {
            "replies": [
                {"presence_stats": {"num_clients": 2, "num_users": 1}},
                {"presence_stats": {}},  # нули Centrifugo может опускать
                {"error": {"code": 102, "message": "unknown channel"}},
            ]
        }
        with patch("messenger.clients.centrifugo.requests.post", return_value=http_response(body=body)) as post:
            result = REAL_PRESENCE_STATS_BATCH(["personal:1", "personal:2", "personal:3"])
        post.assert_called_once()
        self.assertEqual(post.call_args.args[0], f"{API_URL}/batch")
        self.assertEqual(post.call_args.kwargs["headers"], {"X-API-Key": "key"})
        payload = post.call_args.kwargs["json"]
        self.assertEqual(
            payload["commands"],
            [{"presence_stats": {"channel": f"personal:{i}"}} for i in (1, 2, 3)],
        )
        self.assertTrue(payload["parallel"])
        self.assertLessEqual(post.call_args.kwargs["timeout"], centrifugo.API_TIMEOUT)
        self.assertEqual(result, {"personal:1": 1, "personal:2": 0, "personal:3": None})

    def test_empty_channel_list_makes_no_request(self):
        with patch("messenger.clients.centrifugo.requests.post") as post:
            self.assertEqual(REAL_PRESENCE_STATS_BATCH([]), {})
        post.assert_not_called()

    def test_errors_raise_centrifugo_error(self):
        cases = (
            {"side_effect": requests.Timeout("slow")},
            {"return_value": http_response(status=500, body={})},
            {"return_value": http_response(body={"error": {"code": 101, "message": "unauthorized"}})},
        )
        for kwargs in cases:
            with patch("messenger.clients.centrifugo.requests.post", **kwargs):
                with self.assertRaises(CentrifugoError, msg=kwargs):
                    REAL_PRESENCE_STATS_BATCH(["personal:1"])

    @override_settings(CENTRIFUGO_API_URL="")
    def test_not_configured(self):
        with self.assertRaises(CentrifugoError):
            REAL_PRESENCE_STATS_BATCH(["personal:1"])


@override_settings(CENTRIFUGO_API_URL=API_URL)
class OnlineUserIdsTests(MessengerTestCase):
    def test_maps_personal_channels_to_online_users(self):
        self.presence_mock.return_value = {"personal:1": 1, "personal:2": 0, "personal:3": None}
        self.assertEqual(presence.online_user_ids([1, 2, 3, 1]), {1})
        channels = self.presence_mock.call_args.args[0]
        self.assertEqual(sorted(channels), ["personal:1", "personal:2", "personal:3"])

    def test_error_means_everyone_offline_and_logs_warning(self):
        self.presence_mock.side_effect = CentrifugoError("down")
        with self.assertLogs("messenger.services.presence", level="WARNING"):
            self.assertEqual(presence.online_user_ids([1, 2]), set())

    def test_failure_trips_presence_down_flag_for_a_while(self):
        self.presence_mock.side_effect = CentrifugoError("down")
        with self.assertLogs("messenger.services.presence", level="WARNING"):
            presence.online_user_ids([1])
        self.presence_mock.reset_mock(side_effect=True)
        self.presence_mock.return_value = {"personal:1": 1}
        # флаг «presence недоступен» в кэше: следующие вызовы не ходят в Centrifugo
        self.assertEqual(presence.online_user_ids([1]), set())
        self.presence_mock.assert_not_called()
        self.assertLessEqual(presence.DOWN_TTL, 60)

        cache.delete(presence.DOWN_KEY)
        self.assertEqual(presence.online_user_ids([1]), {1})

    @override_settings(CENTRIFUGO_API_URL="")
    def test_not_configured_short_circuits_without_warning(self):
        with self.assertNoLogs("messenger.services.presence", level="WARNING"):
            self.assertEqual(presence.online_user_ids([1, 2]), set())
        self.presence_mock.assert_not_called()

    def test_no_users_no_call(self):
        self.assertEqual(presence.online_user_ids([]), set())
        self.presence_mock.assert_not_called()


class TouchTests(MessengerTestCase):
    def setUp(self):
        super().setUp()
        for user in (self.client_user, self.specialist):
            cache.delete(presence.throttle_key(user.pk))
        push_patcher = patch("messenger.services.push.send_push")
        push_patcher.start()
        self.addCleanup(push_patcher.stop)

    def last_active(self, user):
        row = UserPresence.objects.filter(user=user).first()
        return row.last_active_at if row else None

    def test_touch_upserts_at_most_once_per_minute(self):
        presence.touch(self.client_user.pk)
        first = self.last_active(self.client_user)
        self.assertIsNotNone(first)
        presence.touch(self.client_user.pk)
        self.assertEqual(self.last_active(self.client_user), first)  # guard в кэше

        cache.delete(presence.throttle_key(self.client_user.pk))
        UserPresence.objects.filter(user=self.client_user).update(last_active_at=first - timedelta(hours=1))
        presence.touch(self.client_user.pk)
        self.assertGreaterEqual(self.last_active(self.client_user), first)
        self.assertEqual(UserPresence.objects.filter(user=self.client_user).count(), 1)

    def test_touch_never_raises(self):
        with patch("messenger.services.presence.cache.add", side_effect=RuntimeError("redis down")):
            with self.assertLogs("messenger.services.presence", level="WARNING"):
                presence.touch(self.client_user.pk)

    @override_settings(CENTRIFUGO_TOKEN_SECRET="x" * 40)
    def test_connection_token_touches(self):
        self.auth(self.client_user)
        self.assertEqual(self.client.get("/api/messenger/connection-token/").status_code, 200)
        self.assertIsNotNone(self.last_active(self.client_user))

    def test_send_message_touches_sender_only(self):
        self.auth(self.specialist)
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(
                f"/api/chats/{self.chat.channel_id}/messages/", {"text": "hi"}, format="json"
            )
        self.assertEqual(response.status_code, 201, response.content)
        self.assertIsNotNone(self.last_active(self.specialist))
        self.assertIsNone(self.last_active(self.client_user))

    def test_greeting_does_not_touch_specialist(self):
        # приветствие уходит от имени специалиста при создании чата — это не его активность
        specialist = User.objects.create_user(
            username="sp_greet", password="p", role=ROLE_SPECIALIST, invite_greeting="Здравствуйте"
        )
        cache.delete(presence.throttle_key(specialist.pk))
        chat = create_or_get_chat(self.client_user, specialist)
        self.assertTrue(Message.objects.filter(chat=chat, sender=specialist).exists())
        self.assertIsNone(self.last_active(specialist))

    def test_mark_read_touches(self):
        message = Message.objects.create(chat=self.chat, sender=self.specialist, text="x")
        self.auth(self.client_user)
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(
                f"/api/chats/{self.chat.channel_id}/read/", {"lastReadMessageId": message.id}, format="json"
            )
        self.assertEqual(response.status_code, 200, response.content)
        self.assertIsNotNone(self.last_active(self.client_user))


@override_settings(CENTRIFUGO_API_URL=API_URL)
class ChatListPresenceTests(MessengerTestCase):
    def setUp(self):
        super().setUp()
        self.sp2 = User.objects.create_user(username="sp_presence", password="p", role=ROLE_SPECIALIST)
        self.chat2 = create_or_get_chat(self.client_user, self.sp2)

    def get_list(self, user):
        self.auth(user)
        response = self.client.get("/api/chats/")
        self.assertEqual(response.status_code, 200, response.content)
        return {item["channelId"]: item for item in response.json()}

    def test_is_online_and_last_active_at_with_one_batch_call(self):
        seen = timezone.now() - timedelta(minutes=5)
        UserPresence.objects.create(user=self.specialist, last_active_at=seen)
        self.presence_mock.return_value = {f"personal:{self.specialist.pk}": 1, f"personal:{self.sp2.pk}": 0}

        items = self.get_list(self.client_user)

        self.presence_mock.assert_called_once()
        self.assertEqual(
            sorted(self.presence_mock.call_args.args[0]),
            sorted([f"personal:{self.specialist.pk}", f"personal:{self.sp2.pk}"]),
        )
        first = items[self.chat.channel_id]["companion"]
        self.assertTrue(first["isOnline"])
        self.assertEqual(first["lastActiveAt"], events.format_datetime(seen))
        second = items[self.chat2.channel_id]["companion"]
        self.assertFalse(second["isOnline"])
        self.assertIsNone(second["lastActiveAt"])

    def test_list_survives_centrifugo_failure(self):
        self.presence_mock.side_effect = CentrifugoError("down")
        items = self.get_list(self.client_user)
        self.assertEqual(len(items), 2)
        self.assertTrue(all(item["companion"]["isOnline"] is False for item in items.values()))

    def test_retrieve_has_presence(self):
        self.presence_mock.return_value = {f"personal:{self.specialist.pk}": 2}
        self.auth(self.client_user)
        response = self.client.get(f"/api/chats/{self.chat.channel_id}/")
        self.assertEqual(response.status_code, 200, response.content)
        self.assertTrue(response.json()["companion"]["isOnline"])
        self.presence_mock.assert_called_once_with([f"personal:{self.specialist.pk}"])

    def test_last_active_at_adds_no_queries(self):
        self.auth(self.client_user)

        def count():
            with CaptureQueriesContext(connection) as ctx:
                self.client.get("/api/chats/")
            return len([q for q in ctx.captured_queries if "silk_" not in q["sql"]])

        baseline = count()
        UserPresence.objects.create(user=self.specialist, last_active_at=timezone.now())
        UserPresence.objects.create(user=self.sp2, last_active_at=timezone.now())
        self.assertEqual(count(), baseline)

    def test_chat_updated_does_not_query_presence(self):
        UserPresence.objects.create(user=self.specialist, last_active_at=timezone.now())
        with CaptureQueriesContext(connection) as ctx:
            with self.captureOnCommitCallbacks(execute=True):
                events.publish_chat_updated(self.chat)
        self.presence_mock.assert_not_called()
        self.assertFalse([q for q in ctx.captured_queries if "messenger_userpresence" in q["sql"]])

    def test_presence_only_for_first_chats_of_list(self):
        UserPresence.objects.create(user=self.sp2, last_active_at=timezone.now())
        self.presence_mock.return_value = {f"personal:{self.specialist.pk}": 1, f"personal:{self.sp2.pk}": 1}
        # порядок списка: chat2 (новее) первым
        with patch("chat_access.services.chat_list.PRESENCE_LIST_LIMIT", 1):
            items = self.get_list(self.client_user)
        self.presence_mock.assert_called_once_with([f"personal:{self.sp2.pk}"])
        self.assertTrue(items[self.chat2.channel_id]["companion"]["isOnline"])
        self.assertFalse(items[self.chat.channel_id]["companion"]["isOnline"])
        # lastActiveAt — для всех (из той же выборки, без Centrifugo)
        self.assertIsNotNone(items[self.chat2.channel_id]["companion"]["lastActiveAt"])

    def test_blacklist_does_not_change_presence(self):
        # ЧС — только «не беспокоить»: клиент не должен по статусу понять, что он в ЧС
        BlockedChat.objects.create(user=self.specialist, chat=self.chat)
        seen = timezone.now() - timedelta(minutes=3)
        UserPresence.objects.create(user=self.specialist, last_active_at=seen)
        UserPresence.objects.create(user=self.client_user, last_active_at=seen)
        self.presence_mock.return_value = {
            f"personal:{self.specialist.pk}": 1, f"personal:{self.sp2.pk}": 1, f"personal:{self.client_user.pk}": 1,
        }
        items = self.get_list(self.client_user)
        companion = items[self.chat.channel_id]["companion"]
        self.assertTrue(companion["isOnline"])
        self.assertEqual(companion["lastActiveAt"], events.format_datetime(seen))
        self.assertIn(f"personal:{self.specialist.pk}", self.presence_mock.call_args.args[0])
        self.assertFalse(items[self.chat.channel_id]["isBlocked"])
        # retrieve — так же
        self.auth(self.client_user)
        companion = self.client.get(f"/api/chats/{self.chat.channel_id}/").json()["companion"]
        self.assertTrue(companion["isOnline"])
        self.assertEqual(companion["lastActiveAt"], events.format_datetime(seen))
        # специалист статус клиента видит как обычно
        [item] = self.get_list(self.specialist).values()
        self.assertTrue(item["companion"]["isOnline"])
        self.assertIsNotNone(item["companion"]["lastActiveAt"])
