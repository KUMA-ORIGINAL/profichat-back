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
from messenger.models import ChatMember
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

    def test_chat_list_read_positions_of_viewer_and_companion(self):
        first = self.send(self.specialist, "first")
        reply = self.send(self.client_user, "reply")
        [item] = self.get_list(self.client_user)
        self.assertIsNone(item["lastReadMessageId"])
        self.assertIsNone(item["companionLastReadMessageId"])
        self.assertIsNone(item["pinnedAt"])

        ChatMember.objects.filter(chat=self.chat, user=self.client_user).update(last_read_message_id=first.id)
        ChatMember.objects.filter(chat=self.chat, user=self.specialist).update(last_read_message_id=reply.id)

        [item] = self.get_list(self.client_user)
        self.assertEqual(item["lastReadMessageId"], first.id)
        self.assertEqual(item["companionLastReadMessageId"], reply.id)
        [item] = self.get_list(self.specialist)
        self.assertEqual(item["lastReadMessageId"], reply.id)
        self.assertEqual(item["companionLastReadMessageId"], first.id)

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
        ChatMember.objects.filter(user=self.client_user).update(pinned_at=timezone.now())
        self.assertEqual(len(self._app_queries()), baseline)
        self.assertLessEqual(baseline, 8)  # +1 запрос: вложения последнего сообщения


class ChatPinTests(MessengerTestCase):
    def setUp(self):
        super().setUp()
        patcher = patch("messenger.services.push.send_push")
        patcher.start()
        self.addCleanup(patcher.stop)
        self.sp_old = User.objects.create_user(username="sp_pin_old", password="p", role=ROLE_SPECIALIST)
        self.sp_mid = User.objects.create_user(username="sp_pin_mid", password="p", role=ROLE_SPECIALIST)
        self.chat_old = create_or_get_chat(self.client_user, self.sp_old)
        self.chat_mid = create_or_get_chat(self.client_user, self.sp_mid)
        # порядок по последнему сообщению: self.chat, chat_mid, chat_old
        message_service.send_message(self.chat_old, self.sp_old, text="old")
        message_service.send_message(self.chat_mid, self.sp_mid, text="mid")
        message_service.send_message(self.chat, self.specialist, text="new")

    def post(self, user, action, channel_id):
        self.auth(user)
        with self.captureOnCommitCallbacks(execute=True):
            return self.client.post(f"/api/chats/pins/{action}/", {"channelId": channel_id}, format="json")

    def ids(self, user, **params):
        self.auth(user)
        response = self.client.get("/api/chats/", params)
        self.assertEqual(response.status_code, 200, response.content)
        body = response.json()
        items = body["results"] if isinstance(body, dict) else body
        return [item["channelId"] for item in items], items

    def chat_updated_events(self):
        return [
            call.args for call in self.broadcast_mock.call_args_list
            if call.args[1]["type"] == "chat.updated"
        ]

    def test_pin_sets_pinned_at_and_notifies_own_devices(self):
        self.broadcast_mock.reset_mock()
        response = self.post(self.client_user, "add", self.chat_old.channel_id)

        self.assertEqual(response.status_code, 200, response.content)
        body = response.json()
        self.assertEqual(body["channelId"], self.chat_old.channel_id)
        self.assertIsNotNone(body["pinnedAt"])
        member = ChatMember.objects.get(chat=self.chat_old, user=self.client_user)
        self.assertIsNotNone(member.pinned_at)
        # у собеседника закрепление своё
        self.assertIsNone(ChatMember.objects.get(chat=self.chat_old, user=self.sp_old).pinned_at)

        [(channels, envelope)] = self.chat_updated_events()
        self.assertEqual(channels, [f"personal:{self.client_user.id}"])
        self.assertEqual(envelope["data"]["channelId"], self.chat_old.channel_id)
        self.assertEqual(envelope["data"]["pinnedAt"], body["pinnedAt"])

    def test_pin_is_idempotent_and_keeps_original_time(self):
        first = self.post(self.client_user, "add", self.chat_old.channel_id).json()["pinnedAt"]
        second = self.post(self.client_user, "add", self.chat_old.channel_id).json()["pinnedAt"]
        self.assertEqual(first, second)

    def test_unpin(self):
        self.post(self.client_user, "add", self.chat_old.channel_id)
        self.broadcast_mock.reset_mock()
        response = self.post(self.client_user, "remove", self.chat_old.channel_id)
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json(), {"status": "success", "deleted": True})
        self.assertIsNone(ChatMember.objects.get(chat=self.chat_old, user=self.client_user).pinned_at)
        [(channels, envelope)] = self.chat_updated_events()
        self.assertEqual(channels, [f"personal:{self.client_user.id}"])
        self.assertIsNone(envelope["data"]["pinnedAt"])

        response = self.post(self.client_user, "remove", self.chat_old.channel_id)
        self.assertEqual(response.json(), {"status": "success", "deleted": False})

    def test_pinned_chats_first_newest_pin_first(self):
        self.post(self.client_user, "add", self.chat_old.channel_id)
        ChatMember.objects.filter(chat=self.chat_old, user=self.client_user).update(
            pinned_at=timezone.now() - timedelta(hours=1)
        )
        self.post(self.client_user, "add", self.chat_mid.channel_id)

        ids, items = self.ids(self.client_user)
        self.assertEqual(ids, [self.chat_mid.channel_id, self.chat_old.channel_id, self.chat.channel_id])
        self.assertIsNotNone(items[0]["pinnedAt"])
        self.assertIsNone(items[2]["pinnedAt"])

        # закрепление клиента не влияет на список специалиста
        [item] = self.ids(self.sp_old)[1]
        self.assertIsNone(item["pinnedAt"])

    def test_pinned_order_with_access_status_filter(self):
        self.post(self.client_user, "add", self.chat_old.channel_id)
        ids, _ = self.ids(self.client_user, access_status="inactive")
        self.assertEqual(ids[0], self.chat_old.channel_id)

    @override_settings(MESSENGER_LEGACY_MODE=True)
    def test_pinned_first_in_legacy_mode(self):
        with patch("chat_access.services.chat_list.chat_client") as stream_mock:
            stream_mock.query_channels.return_value = {"channels": []}
            stream_mock.channel.return_value.query.return_value = {"messages": []}
            self.post(self.client_user, "add", self.chat_old.channel_id)
            ids, items = self.ids(self.client_user)
        # legacy: незакреплённые по -created_at (chat_mid, self.chat)
        self.assertEqual(ids, [self.chat_old.channel_id, self.chat_mid.channel_id, self.chat.channel_id])
        self.assertIsNotNone(items[0]["pinnedAt"])

    def test_pin_requires_membership(self):
        stranger = User.objects.create_user(username="stranger_pin", password="p", role=ROLE_CLIENT)
        for action in ("add", "remove"):
            response = self.post(stranger, action, self.chat.channel_id)
            self.assertEqual(response.status_code, 404)
            self.assertEqual(response.json()["code"], "CHAT_NOT_FOUND")

    def test_pin_requires_channel_id(self):
        self.auth(self.client_user)
        response = self.client.post("/api/chats/pins/add/", {}, format="json")
        self.assertEqual(response.status_code, 400)

    def test_pin_and_unpin_stamp_pin_changed_at(self):
        member = lambda: ChatMember.objects.get(chat=self.chat_old, user=self.client_user)  # noqa: E731
        self.assertIsNone(member().pin_changed_at)
        self.post(self.client_user, "add", self.chat_old.channel_id)
        pinned_stamp = member().pin_changed_at
        self.assertIsNotNone(pinned_stamp)
        self.post(self.client_user, "remove", self.chat_old.channel_id)
        self.assertGreater(member().pin_changed_at, pinned_stamp)

    def test_specialist_can_pin(self):
        response = self.post(self.specialist, "add", self.chat.channel_id)
        self.assertEqual(response.status_code, 200, response.content)
        self.assertIsNotNone(ChatMember.objects.get(chat=self.chat, user=self.specialist).pinned_at)


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

    def test_chat_updated_payload_does_not_query_stream(self):
        # shouldReply в chat.updated не входит — запрос к GetStream не нужен
        from messenger.services import events

        data = events.chat_updated_payload(self.chat, self.client_user)
        self.assertNotIn("should_reply", data)
        self.stream_mock.channel.assert_not_called()
        self.stream_mock.query_channels.assert_not_called()

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


class ChatCompanionTests(MessengerTestCase):
    """`companion`: отчество; телефон — только специалисту этого чата (телефон клиента)."""

    def setUp(self):
        super().setUp()
        User.objects.filter(pk=self.client_user.pk).update(
            first_name="Иван", last_name="Иванов", middle_name="Иванович", phone_number="+996700111222"
        )
        User.objects.filter(pk=self.specialist.pk).update(
            first_name="Анна", last_name="Петрова", middle_name="Сергеевна", phone_number="+996700333444"
        )

    def companion(self, user, retrieve=False):
        self.auth(user)
        url = f"/api/chats/{self.chat.channel_id}/" if retrieve else "/api/chats/"
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200, response.content)
        body = response.json()
        return (body if retrieve else body[0])["companion"]

    def test_specialist_sees_client_middle_name_and_phone(self):
        for retrieve in (False, True):
            companion = self.companion(self.specialist, retrieve)
            self.assertEqual(companion["id"], self.client_user.id)
            self.assertEqual(companion["firstName"], "Иван")
            self.assertEqual(companion["middleName"], "Иванович")
            self.assertEqual(companion["phoneNumber"], "+996700111222")
            self.assertIn("photo", companion)

    def test_client_sees_specialist_middle_name_but_not_phone(self):
        for retrieve in (False, True):
            companion = self.companion(self.client_user, retrieve)
            self.assertEqual(companion["id"], self.specialist.id)
            self.assertEqual(companion["middleName"], "Сергеевна")
            self.assertIsNone(companion["phoneNumber"])

    @override_settings(DOMAIN="api.example.com")
    def test_companion_photo_is_absolute(self):
        User.objects.filter(pk=self.specialist.pk).update(photo="user/photos/2026/10/27/s.jpg")
        for retrieve in (False, True):
            companion = self.companion(self.client_user, retrieve)
            self.assertEqual(companion["photo"], "https://api.example.com/media/user/photos/2026/10/27/s.jpg")
        # без фото — null
        self.assertIsNone(self.companion(self.specialist)["photo"])

    def test_companion_without_phone(self):
        User.objects.filter(pk=self.client_user.pk).update(phone_number=None, middle_name="")
        companion = self.companion(self.specialist)
        self.assertIsNone(companion["phoneNumber"])
        self.assertEqual(companion["middleName"], "")
