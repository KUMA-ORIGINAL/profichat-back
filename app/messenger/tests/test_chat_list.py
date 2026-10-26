from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from account.models import ROLE_CLIENT, ROLE_SPECIALIST
from chat_access.models import BlockedChat, FavoriteChat
from chat_access.services.chat_commands import create_or_get_chat
from messenger.services import messages as message_service
from messenger.tests.base import MessengerTestCase

User = get_user_model()


class ChatListTests(MessengerTestCase):
    def setUp(self):
        super().setUp()
        patcher = patch("messenger.services.push.send_push")
        patcher.start()
        self.addCleanup(patcher.stop)

    def get_list(self, user):
        self.auth(user)
        response = self.client.get("/api/chats/")
        self.assertEqual(response.status_code, 200, response.content)
        return response.json()

    def send(self, sender, text, chat=None):
        return message_service.send_message(
            chat or self.chat, sender, text=text, client_msg_id=None, reply_to_id=None, attachment_ids=[]
        )

    def test_chat_list_has_last_message_unread_and_should_reply_from_db(self):
        self.send(self.specialist, "first")
        last = self.send(self.specialist, "second")

        with patch("chat_access.services.chat_list.chat_client") as stream_mock:
            [client_item] = self.get_list(self.client_user)
        stream_mock.query_channels.assert_not_called()  # без legacy-режима список не ходит в GetStream
        self.assertEqual(client_item["lastMessage"]["id"], last.id)
        self.assertEqual(client_item["lastMessage"]["text"], "second")
        self.assertEqual(client_item["lastMessage"]["channelId"], self.chat.channel_id)
        self.assertIsNotNone(client_item["lastMessageAt"])
        self.assertEqual(client_item["unreadCount"], 2)
        self.assertTrue(client_item["shouldReply"])
        self.assertFalse(client_item["isFavorite"])
        self.assertFalse(client_item["isBlocked"])
        self.assertTrue(client_item["clientCanSendVoice"])
        self.assertIsNone(client_item["tariff"])

        [specialist_item] = self.get_list(self.specialist)
        self.assertEqual(specialist_item["unreadCount"], 0)
        self.assertFalse(specialist_item["shouldReply"])

        # системное последнее сообщение — отвечать не нужно
        message_service.create_system_message(self.chat, "tariffExpired", "Срок действия тарифа истёк.")
        [client_item] = self.get_list(self.client_user)
        self.assertFalse(client_item["shouldReply"])
        self.assertEqual(client_item["lastMessage"]["type"], "system")

    def test_chat_list_without_messages(self):
        [item] = self.get_list(self.client_user)
        self.assertIsNone(item["lastMessage"])
        self.assertIsNone(item["lastMessageAt"])
        self.assertEqual(item["unreadCount"], 0)
        self.assertFalse(item["shouldReply"])

    def test_chat_list_sorted_by_last_message_at(self):
        other_specialist = User.objects.create_user(username="sp_2", password="p", role=ROLE_SPECIALIST)
        third_specialist = User.objects.create_user(username="sp_3", password="p", role=ROLE_SPECIALIST)
        older_chat = create_or_get_chat(self.client_user, other_specialist)
        empty_chat = create_or_get_chat(self.client_user, third_specialist)  # самый новый, без сообщений

        self.send(other_specialist, "old", chat=older_chat)
        self.send(self.specialist, "new")
        ids = [item["channelId"] for item in self.get_list(self.client_user)]
        self.assertEqual(ids, [self.chat.channel_id, older_chat.channel_id, empty_chat.channel_id])

        self.send(other_specialist, "newest", chat=older_chat)
        ids = [item["channelId"] for item in self.get_list(self.client_user)]
        self.assertEqual(ids, [older_chat.channel_id, self.chat.channel_id, empty_chat.channel_id])

    def test_chat_list_tariff_block(self):
        order = self.activate_tariff(hours=5)
        for user in (self.client_user, self.specialist):
            [item] = self.get_list(user)
            self.assertEqual(item["tariff"]["name"], "Тестовый тариф")
            self.assertIsNotNone(item["tariff"]["activatedAt"])
            self.assertIsNotNone(item["tariff"]["expiresAt"])

        # истёкший тариф остаётся в блоке (как extraData канала в Stream): клиент сравнивает expiresAt
        order.expires_at = timezone.now() - timedelta(minutes=1)
        order.save(update_fields=["expires_at"])
        [item] = self.get_list(self.client_user)
        self.assertEqual(item["tariff"]["name"], "Тестовый тариф")

    def test_chat_list_favorite_and_blocked_flags(self):
        FavoriteChat.objects.create(user=self.specialist, chat=self.chat)
        BlockedChat.objects.create(user=self.specialist, chat=self.chat)
        [item] = self.get_list(self.specialist)
        self.assertTrue(item["isFavorite"])
        self.assertTrue(item["isBlocked"])
        [item] = self.get_list(self.client_user)
        self.assertFalse(item["isFavorite"])
        self.assertFalse(item["isBlocked"])

    def _app_queries(self):
        """Запросы приложения к БД (без служебных запросов silk при DEBUG)."""
        with CaptureQueriesContext(connection) as ctx:
            self.client.get("/api/chats/")
        return [
            q["sql"] for q in ctx.captured_queries
            if q["sql"].startswith("SELECT") and "silk_" not in q["sql"]
        ]

    def test_chat_list_query_count_does_not_grow_with_chats(self):
        self.send(self.specialist, "hi")
        self.auth(self.client_user)
        baseline = len(self._app_queries())
        for i in range(3):
            specialist = User.objects.create_user(username=f"sp_n{i}", password="p", role=ROLE_SPECIALIST)
            chat = create_or_get_chat(self.client_user, specialist)
            self.send(specialist, "msg", chat=chat)
        self.assertEqual(len(self._app_queries()), baseline)
        self.assertLessEqual(baseline, 8)  # +1 запрос: вложения последнего сообщения


def stream_channels(chat, sender_id, message_type="regular"):
    """Ответ GetStream query_channels с одним последним сообщением канала."""
    return {
        "channels": [
            {
                "channel": {"id": chat.channel_id},
                "messages": [{"type": message_type, "user": {"id": str(sender_id)}, "text": "message"}],
            }
        ]
    }


@override_settings(MESSENGER_LEGACY_MODE=True)
class LegacyModeChatListTests(MessengerTestCase):
    """
    MESSENGER_LEGACY_MODE=True (до переключения): старое приложение пишет только в GetStream,
    поэтому shouldReply считается по GetStream, а порядок чатов — как до мессенджера (-created_at).
    """

    def setUp(self):
        super().setUp()
        patcher = patch("chat_access.services.chat_list.chat_client")
        self.stream_mock = patcher.start()
        self.addCleanup(patcher.stop)
        push_patcher = patch("messenger.services.push.send_push")
        push_patcher.start()
        self.addCleanup(push_patcher.stop)

    def get_list(self, user):
        self.auth(user)
        response = self.client.get("/api/chats/")
        self.assertEqual(response.status_code, 200, response.content)
        return response.json()

    def test_should_reply_from_stream_not_db(self):
        # в нашей БД последнее сообщение от клиента, а в Stream (старое приложение) — от специалиста
        message_service.send_message(self.chat, self.client_user, text="из нового приложения")
        self.stream_mock.query_channels.return_value = stream_channels(self.chat, self.specialist.pk)

        [item] = self.get_list(self.client_user)

        self.assertTrue(item["shouldReply"])
        kwargs = self.stream_mock.query_channels.call_args.kwargs
        self.assertEqual(kwargs["filter_conditions"]["id"], {"$in": [self.chat.channel_id]})

    def test_should_reply_false_for_own_or_system_stream_message(self):
        for sender_id, message_type in ((self.client_user.pk, "regular"), (self.specialist.pk, "system")):
            self.stream_mock.query_channels.return_value = stream_channels(self.chat, sender_id, message_type)
            [item] = self.get_list(self.client_user)
            self.assertFalse(item["shouldReply"], (sender_id, message_type))

    def test_should_reply_false_when_stream_fails(self):
        message_service.send_message(self.chat, self.specialist, text="привет")  # по БД было бы True
        self.stream_mock.query_channels.side_effect = RuntimeError("stream down")

        [item] = self.get_list(self.client_user)

        self.assertFalse(item["shouldReply"])

    def test_retrieve_uses_stream(self):
        self.stream_mock.query_channels.return_value = stream_channels(self.chat, self.specialist.pk)
        self.auth(self.client_user)
        response = self.client.get(f"/api/chats/{self.chat.channel_id}/")
        self.assertEqual(response.status_code, 200, response.content)
        self.assertTrue(response.json()["shouldReply"])

    def test_chat_order_by_created_at(self):
        self.stream_mock.query_channels.return_value = {"channels": []}
        newer_specialist = User.objects.create_user(username="sp_new", password="p", role=ROLE_SPECIALIST)
        newer_chat = create_or_get_chat(self.client_user, newer_specialist)
        # сообщение в старом чате: по last_message_at он был бы первым
        message_service.send_message(self.chat, self.specialist, text="свежее")

        ids = [item["channelId"] for item in self.get_list(self.client_user)]

        self.assertEqual(ids, [newer_chat.channel_id, self.chat.channel_id])


class ChatRetrieveTests(MessengerTestCase):
    def test_retrieve_by_channel_id(self):
        self.auth(self.client_user)
        response = self.client.get(f"/api/chats/{self.chat.channel_id}/")
        self.assertEqual(response.status_code, 200, response.content)
        body = response.json()
        self.assertEqual(body["channelId"], self.chat.channel_id)
        self.assertEqual(body["companion"]["id"], self.specialist.id)
        self.assertIn("unreadCount", body)
        self.assertIn("tariff", body)

    def test_retrieve_non_member_404(self):
        stranger = User.objects.create_user(username="stranger", password="p", role=ROLE_CLIENT)
        self.auth(stranger)
        response = self.client.get(f"/api/chats/{self.chat.channel_id}/")
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["code"], "CHAT_NOT_FOUND")
