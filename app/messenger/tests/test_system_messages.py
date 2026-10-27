from datetime import timedelta
from unittest.mock import AsyncMock, patch

from django.contrib.auth import get_user_model
from django.test import override_settings
from django.utils import timezone

from account.models import ROLE_CLIENT, ROLE_SPECIALIST
from account.services.stream import DEFAULT_TEXTS
from account.services.user import broadcast_user_update
from chat_access.models import BlockedChat, FavoriteChat, Tariff
from chat_access.services import update_chat_data_from_order
from chat_access.services.chat_commands import create_or_get_chat
from messenger.models import ChatMember, Message
from messenger.services import access, events, system_messages
from messenger.tests.base import MessengerTestCase

User = get_user_model()

STREAM_EXTRA = "chat_access.services.chat.update_channel_extra_data"
STREAM_EXTRA_FAVORITES = "chat_access.services.favorites.update_channel_extra_data"


class EventsMixin:
    def events_of_type(self, event_type):
        return [
            call.args for call in self.broadcast_mock.call_args_list
            if call.args[1]["type"] == event_type
        ]

    def event_for(self, event_type, user):
        channel = events.personal_channel(user.pk)
        found = [data for channels, data in self.events_of_type(event_type) if channel in channels]
        self.assertEqual(len(found), 1, f"{event_type} для {user.pk}: {found}")
        return found[0]["data"]


class SystemMessageServiceTestCase(MessengerTestCase):
    def setUp(self):
        super().setUp()
        self.client_user.first_name, self.client_user.last_name = "Иван", "Клиентов"
        self.client_user.save()
        self.specialist.first_name, self.specialist.last_name = "Анна", "Врачева"
        self.specialist.save()
        self.chat.refresh_from_db()

    def test_system_message_created_with_default_text_and_names(self):
        message = system_messages.send_system_message_once(self.chat, "tariffActivated")

        self.assertIsNotNone(message)
        self.assertEqual(message.type, Message.Type.SYSTEM)
        self.assertIsNone(message.sender_id)
        self.assertEqual(message.custom_type, "tariffActivated")
        self.assertEqual(message.text, DEFAULT_TEXTS["tariffActivated"])
        self.assertEqual(
            message.extra_data,
            {
                "customType": "tariffActivated",
                "clientName": "Иван Клиентов",
                "specialistName": "Анна Врачева",
            },
        )
        self.chat.refresh_from_db()
        self.assertEqual(self.chat.last_message_id, message.id)

    def test_system_message_custom_text(self):
        message = system_messages.send_system_message_once(self.chat, "chatBlocked", "Свой текст")
        self.assertEqual(message.text, "Свой текст")

    def test_system_message_dedup_within_600s(self):
        first = system_messages.send_system_message_once(self.chat, "tariffExpired")
        second = system_messages.send_system_message_once(self.chat, "tariffExpired")

        self.assertIsNotNone(first)
        self.assertIsNone(second)
        self.assertEqual(Message.objects.filter(chat=self.chat, custom_type="tariffExpired").count(), 1)

        # другой тип не дедуплицируется
        self.assertIsNotNone(system_messages.send_system_message_once(self.chat, "tariffActivated"))

        # через 600 с — снова можно
        Message.objects.filter(pk=first.pk).update(created_at=timezone.now() - timedelta(seconds=601))
        self.assertIsNotNone(system_messages.send_system_message_once(self.chat, "tariffExpired"))
        self.assertEqual(Message.objects.filter(chat=self.chat, custom_type="tariffExpired").count(), 2)

    def test_dedup_is_per_chat(self):
        other_client = User.objects.create_user(username="client_2", password="pass", role=ROLE_CLIENT)
        other_chat = create_or_get_chat(other_client, self.specialist)

        self.assertIsNotNone(system_messages.send_system_message_once(self.chat, "tariffExpired"))
        self.assertIsNotNone(system_messages.send_system_message_once(other_chat, "tariffExpired"))

    def test_system_message_invalid_type_rejected(self):
        result = system_messages.send_system_message_once(self.chat, "somethingElse")

        self.assertIsNone(result)
        self.assertFalse(Message.objects.filter(chat=self.chat).exists())

    def test_system_message_publishes_message_new_without_unread(self):
        with self.captureOnCommitCallbacks(execute=True):
            message = system_messages.send_system_message_once(self.chat, "tariffProvided")

        published = [c.args for c in self.broadcast_mock.call_args_list if c.args[1]["type"] == "message.new"]
        self.assertEqual(len(published), 1)
        self.assertEqual(published[0][1]["data"]["id"], message.id)
        self.assertEqual(published[0][1]["data"]["customType"], "tariffProvided")
        self.assertEqual(ChatMember.objects.get(chat=self.chat, user=self.client_user).unread_count, 0)


class SystemMessageApiTestCase(MessengerTestCase):
    def url(self, chat=None):
        return f"/api/chats/{(chat or self.chat).channel_id}/system-messages/"

    def test_member_sends_system_message_without_tariff(self):
        self.assertFalse(access.has_active_tariff(self.chat))
        self.auth(self.client_user)

        response = self.client.post(self.url(), {"customType": "tariffExpired"}, format="json")

        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(
            response.json(),
            {
                "success": True,
                "clientName": self.client_user.get_full_name(),
                "specialistName": self.specialist.get_full_name(),
            },
        )
        message = Message.objects.get(chat=self.chat)
        self.assertEqual(message.custom_type, "tariffExpired")
        self.assertEqual(message.text, DEFAULT_TEXTS["tariffExpired"])

    def test_duplicate_returns_success_false(self):
        self.auth(self.specialist)
        self.client.post(self.url(), {"customType": "chatBlocked", "text": "x"}, format="json")
        response = self.client.post(self.url(), {"customType": "chatBlocked", "text": "x"}, format="json")

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["success"])
        self.assertEqual(Message.objects.filter(chat=self.chat).count(), 1)

    def test_invalid_type_rejected_by_api(self):
        self.auth(self.client_user)
        response = self.client.post(self.url(), {"customType": "hack"}, format="json")

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["code"], "VALIDATION_ERROR")
        self.assertFalse(Message.objects.filter(chat=self.chat).exists())

    def test_non_member_gets_404(self):
        outsider = User.objects.create_user(username="outsider", password="pass", role=ROLE_CLIENT)
        self.auth(outsider)
        response = self.client.post(self.url(), {"customType": "tariffExpired"}, format="json")

        self.assertEqual(response.status_code, 404)
        self.assertFalse(Message.objects.filter(chat=self.chat).exists())

    def test_unauthenticated_rejected(self):
        response = self.client.post(self.url(), {"customType": "tariffExpired"}, format="json")
        self.assertEqual(response.status_code, 401)

    @patch("chat_access.views.stream_system_message.send_system_message_once", return_value=True)
    def test_legacy_stream_endpoint_also_writes_to_db(self, stream_send_mock):
        self.auth(self.client_user)
        response = self.client.post(
            "/api/stream/send-system-message/",
            {"channelId": self.chat.channel_id, "customType": "tariffExpired"},
            format="json",
        )

        self.assertEqual(response.status_code, 200, response.content)
        self.assertTrue(response.json()["success"])
        stream_send_mock.assert_called_once_with(self.chat.channel_id, "tariffExpired", None)
        self.assertEqual(Message.objects.filter(chat=self.chat, custom_type="tariffExpired").count(), 1)

    @patch("chat_access.views.stream_system_message.send_system_message_once", return_value=True)
    def test_legacy_stream_endpoint_survives_db_write_failure(self, stream_send_mock):
        self.auth(self.client_user)
        with patch(
            "chat_access.views.stream_system_message.messenger_system_messages.send_system_message_once",
            side_effect=RuntimeError("db down"),
        ):
            response = self.client.post(
                "/api/stream/send-system-message/",
                {"channelId": self.chat.channel_id, "customType": "tariffExpired"},
                format="json",
            )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["success"])


class GreetingTestCase(MessengerTestCase):
    def setUp(self):
        super().setUp()
        self.greeting_specialist = User.objects.create_user(
            username="specialist_greeting",
            password="pass",
            role=ROLE_SPECIALIST,
            invite_greeting="Здравствуйте! Чем могу помочь?",
        )
        self.new_client = User.objects.create_user(username="client_new", password="pass", role=ROLE_CLIENT)

    def test_greeting_created_without_tariff(self):
        chat = create_or_get_chat(self.new_client, self.greeting_specialist)

        self.assertFalse(access.has_active_tariff(chat))
        message = Message.objects.get(chat=chat)
        self.assertEqual(message.type, Message.Type.REGULAR)
        self.assertEqual(message.sender_id, self.greeting_specialist.pk)
        self.assertEqual(message.text, "Здравствуйте! Чем могу помочь?")
        chat.refresh_from_db()
        self.assertEqual(chat.last_message_id, message.id)
        self.assertEqual(ChatMember.objects.get(chat=chat, user=self.new_client).unread_count, 1)

    @override_settings(MESSENGER_LEGACY_MODE=True)
    def test_greeting_without_push_in_legacy_mode(self):
        # старое приложение уже получает пуш приветствия от Stream и пуш-приглашение
        with patch("messenger.tasks.send_message_push.delay") as push_mock, \
                self.captureOnCommitCallbacks(execute=True):
            chat = create_or_get_chat(self.new_client, self.greeting_specialist)

        push_mock.assert_not_called()
        message = Message.objects.get(chat=chat)
        self.assertEqual(ChatMember.objects.get(chat=chat, user=self.new_client).unread_count, 1)
        self.assertIn("message.new", [c.args[1]["type"] for c in self.broadcast_mock.call_args_list])
        self.assertEqual(message.text, "Здравствуйте! Чем могу помочь?")

    def test_greeting_pushed_after_cutover(self):
        with patch("messenger.tasks.send_message_push.delay") as push_mock, \
                self.captureOnCommitCallbacks(execute=True):
            chat = create_or_get_chat(self.new_client, self.greeting_specialist)

        push_mock.assert_called_once_with(Message.objects.get(chat=chat).pk)

    def test_greeting_sent_only_once(self):
        create_or_get_chat(self.new_client, self.greeting_specialist)
        chat = create_or_get_chat(self.new_client, self.greeting_specialist)

        self.assertEqual(Message.objects.filter(chat=chat).count(), 1)

    def test_no_greeting_when_empty(self):
        # базовый специалист без приветствия: чат из setUp пуст
        self.assertFalse(Message.objects.filter(chat=self.chat).exists())

    def test_stream_first_message_still_sent(self):
        with patch("chat_access.services.chat_commands.create_stream_channel") as stream_mock:
            chat = create_or_get_chat(self.new_client, self.greeting_specialist)
        stream_mock.assert_called_once_with(chat, first_message="Здравствуйте! Чем могу помочь?")

    @patch("account.services.invite_client._safe_send_invitation", return_value=("push", {"ok": True}))
    @patch("account.services.invite_client.create_stream_channel")
    @patch(STREAM_EXTRA)
    def test_invite_client_creates_greeting(self, _extra_mock, stream_mock, _send_mock):
        from account.services.invite_client import invite_client

        tariff = Tariff.objects.create(
            name="Бесплатный", price=0, duration_hours=24, is_active=True, specialist=self.greeting_specialist
        )
        chat, _delivery = invite_client("+996555123456", tariff.id, self.greeting_specialist)

        message = Message.objects.get(chat=chat)
        self.assertEqual(message.sender_id, self.greeting_specialist.pk)
        self.assertEqual(message.text, "Здравствуйте! Чем могу помочь?")
        stream_mock.assert_called_once()


class ChatUpdatedEventTestCase(EventsMixin, MessengerTestCase):
    def setUp(self):
        super().setUp()
        patcher = patch(STREAM_EXTRA)
        self.stream_extra_mock = patcher.start()
        self.addCleanup(patcher.stop)
        favorites_patcher = patch(STREAM_EXTRA_FAVORITES)
        self.stream_favorites_mock = favorites_patcher.start()
        self.addCleanup(favorites_patcher.stop)
        self.chat.specialist_note = "заметка"
        self.chat.save(update_fields=["specialist_note"])

    def post(self, user, url, payload):
        self.auth(user)
        with self.captureOnCommitCallbacks(execute=True):
            return self.client.post(url, payload, format="json")

    def test_favorite_publishes_chat_updated(self):
        response = self.post(
            self.specialist, "/api/chats/favorites/add/", {"channelId": self.chat.channel_id}
        )
        self.assertEqual(response.status_code, 200, response.content)

        specialist_data = self.event_for("chat.updated", self.specialist)
        client_data = self.event_for("chat.updated", self.client_user)
        self.assertEqual(
            specialist_data,
            {
                "channelId": self.chat.channel_id,
                "specialistNote": "заметка",
                "clientCanSendVoice": self.chat.client_can_send_voice,
                "tariff": None,
                "isFavorite": True,
                "isBlocked": False,
                "pinnedAt": None,
            },
        )
        self.assertNotIn("specialistNote", client_data)
        self.assertFalse(client_data["isFavorite"])
        self.assertEqual(client_data["channelId"], self.chat.channel_id)
        # Stream по-прежнему синхронизируется
        self.stream_favorites_mock.assert_called_once()

    def test_favorite_remove_publishes_chat_updated(self):
        FavoriteChat.objects.create(user=self.specialist, chat=self.chat)
        self.post(self.specialist, "/api/chats/favorites/remove/", {"channelId": self.chat.channel_id})

        self.assertFalse(self.event_for("chat.updated", self.specialist)["isFavorite"])

    @patch("chat_access.views.chat.mute_user_for_user")
    def test_blacklist_publishes_chat_updated(self, _mute_mock):
        self.post(self.specialist, "/api/chats/blacklist/add/", {"channelId": self.chat.channel_id})

        self.assertTrue(self.event_for("chat.updated", self.specialist)["isBlocked"])
        self.assertFalse(self.event_for("chat.updated", self.client_user)["isBlocked"])

    @patch("chat_access.views.chat.unmute_user_for_user")
    def test_blacklist_remove_publishes_chat_updated(self, _unmute_mock):
        BlockedChat.objects.create(user=self.specialist, chat=self.chat)
        self.post(self.specialist, "/api/chats/blacklist/remove/", {"channelId": self.chat.channel_id})

        self.assertFalse(self.event_for("chat.updated", self.specialist)["isBlocked"])

    @patch("chat_access.services.chat_commands.update_channel_extra_data")
    def test_chat_update_publishes_chat_updated(self, _stream_mock):
        self.auth(self.specialist)
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.patch(
                f"/api/chats/{self.chat.pk}/",
                {"specialistNote": "новая", "clientCanSendVoice": False},
                format="json",
            )
        self.assertEqual(response.status_code, 200, response.content)

        specialist_data = self.event_for("chat.updated", self.specialist)
        self.assertEqual(specialist_data["specialistNote"], "новая")
        self.assertFalse(specialist_data["clientCanSendVoice"])
        self.assertFalse(self.event_for("chat.updated", self.client_user)["clientCanSendVoice"])

    @patch("chat_access.services.chat_commands.update_channel_extra_data", side_effect=RuntimeError("stream"))
    def test_chat_update_publishes_even_if_stream_fails(self, _stream_mock):
        self.auth(self.specialist)
        with self.captureOnCommitCallbacks(execute=True):
            self.client.patch(f"/api/chats/{self.chat.pk}/", {"specialistNote": "x"}, format="json")

        self.assertEqual(self.event_for("chat.updated", self.specialist)["specialistNote"], "x")

    def test_order_update_publishes_tariff(self):
        order = self.activate_tariff(hours=48)
        with self.captureOnCommitCallbacks(execute=True):
            update_chat_data_from_order(order)

        data = self.event_for("chat.updated", self.client_user)
        self.assertEqual(data["tariff"]["name"], "Тестовый тариф")
        self.assertIsNotNone(data["tariff"]["expiresAt"])
        self.assertIsNotNone(data["tariff"]["activatedAt"])
        self.stream_extra_mock.assert_called_once()


class UserUpdatedEventTestCase(EventsMixin, MessengerTestCase):
    @patch("account.services.user.get_channel_layer")
    def test_user_update_published_to_companions(self, layer_mock):
        layer_mock.return_value.group_send = AsyncMock()
        other_specialist = User.objects.create_user(
            username="specialist_2", password="pass", role=ROLE_SPECIALIST
        )
        create_or_get_chat(self.client_user, other_specialist)

        with self.captureOnCommitCallbacks(execute=True):
            broadcast_user_update(self.client_user, changes=["first_name"])

        published = self.events_of_type("chat.user_updated")
        self.assertEqual(len(published), 1)
        channels, envelope = published[0]
        self.assertCountEqual(
            channels,
            [events.personal_channel(self.specialist.pk), events.personal_channel(other_specialist.pk)],
        )
        self.assertNotIn(events.personal_channel(self.client_user.pk), channels)
        data = envelope["data"]
        self.assertEqual(data["user"]["id"], self.client_user.pk)
        self.assertEqual(data["changes"], ["first_name"])
        self.assertIn("schedule", data)
        self.assertIn("nonWorkingDates", data)
        # Django Channels по-прежнему получает user_update
        self.assertEqual(layer_mock.return_value.group_send.call_count, 2)

    PRIVATE_KEYS = {"balance", "birthdate", "gender", "applicationStatus", "showInSearch", "inviteGreeting"}

    @patch("account.services.user.get_channel_layer")
    def test_client_profile_to_specialists_has_phone_but_no_private_fields(self, layer_mock):
        layer_mock.return_value.group_send = AsyncMock()
        User.objects.filter(pk=self.client_user.pk).update(
            phone_number="+996700111222", middle_name="Иванович", balance=500
        )
        self.client_user.refresh_from_db()
        with self.captureOnCommitCallbacks(execute=True):
            broadcast_user_update(self.client_user, changes=["first_name"])

        [(channels, envelope)] = self.events_of_type("chat.user_updated")
        self.assertEqual(channels, [events.personal_channel(self.specialist.pk)])
        user = envelope["data"]["user"]
        self.assertEqual(user["phoneNumber"], "+996700111222")
        self.assertEqual(user["middleName"], "Иванович")
        self.assertEqual(user["role"], ROLE_CLIENT)
        self.assertFalse(self.PRIVATE_KEYS & set(user), user)
        # старый канал Django Channels — без изменений (полный профиль, как на main)
        legacy = layer_mock.return_value.group_send.call_args.args[1]
        self.assertIn("balance", legacy["user"])

    @patch("account.services.user.get_channel_layer")
    def test_specialist_profile_to_clients_has_no_phone(self, layer_mock):
        layer_mock.return_value.group_send = AsyncMock()
        User.objects.filter(pk=self.specialist.pk).update(phone_number="+996700333444", balance=900)
        self.specialist.refresh_from_db()
        with self.captureOnCommitCallbacks(execute=True):
            broadcast_user_update(self.specialist, changes=["description"])

        [(channels, envelope)] = self.events_of_type("chat.user_updated")
        self.assertEqual(channels, [events.personal_channel(self.client_user.pk)])
        user = envelope["data"]["user"]
        self.assertNotIn("phoneNumber", user)
        self.assertFalse(self.PRIVATE_KEYS & set(user), user)
        for key in ("id", "firstName", "lastName", "middleName", "photo", "role", "description", "profession",
                    "organization", "education", "workExperience", "canAudioCall", "canVideoCall"):
            self.assertIn(key, user)
