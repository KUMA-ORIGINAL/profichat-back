import base64
import uuid
from datetime import timedelta
from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.utils import timezone
from push_notifications.models import GCMDevice

from account.models import ROLE_CLIENT, ROLE_SPECIALIST
from chat_access.services.chat_commands import create_or_get_chat
from messenger.models import ChatMember, Message
from messenger.services import events, messages as message_service
from messenger.tests.base import MessengerTestCase

User = get_user_model()

SEND_PUSH = "messenger.services.push.send_push"


class MessageApiTestCase(MessengerTestCase):
    def setUp(self):
        super().setUp()
        push_patcher = patch(SEND_PUSH)
        self.send_push_mock = push_patcher.start()
        self.addCleanup(push_patcher.stop)

    def messages_url(self, chat=None):
        return f"/api/chats/{(chat or self.chat).channel_id}/messages/"

    def message_url(self, message, chat=None):
        return f"/api/chats/{(chat or self.chat).channel_id}/messages/{message.pk}/"

    def read_url(self, chat=None):
        return f"/api/chats/{(chat or self.chat).channel_id}/read/"

    def post_message(self, user, **payload):
        self.auth(user)
        with self.captureOnCommitCallbacks(execute=True):
            return self.client.post(self.messages_url(), payload, format="json")

    def events_of_type(self, event_type):
        return [
            call.args for call in self.broadcast_mock.call_args_list
            if call.args[1]["type"] == event_type
        ]

    def make_message(self, sender=None, text="hi", created_at=None, **extra):
        return Message.objects.create(
            chat=self.chat,
            sender=sender,
            text=text,
            created_at=created_at or timezone.now(),
            **extra,
        )

    def member(self, user):
        return ChatMember.objects.get(chat=self.chat, user=user)


class SendMessageTests(MessageApiTestCase):
    def test_send_message_returns_201_and_publishes_to_both(self):
        client_msg_id = str(uuid.uuid4())
        response = self.post_message(self.specialist, text="  Здравствуйте  ", clientMsgId=client_msg_id)

        self.assertEqual(response.status_code, 201, response.content)
        body = response.json()
        message = Message.objects.get(pk=body["id"])
        self.assertEqual(message.text, "Здравствуйте")
        self.assertEqual(body["text"], "Здравствуйте")
        self.assertEqual(body["channelId"], self.chat.channel_id)
        self.assertEqual(body["senderId"], self.specialist.id)
        self.assertEqual(body["type"], "regular")
        self.assertEqual(body["clientMsgId"], client_msg_id)
        self.assertEqual(body["attachments"], [])
        self.assertIsNone(body["call"])
        self.assertIsNone(body["replyTo"])

        published = self.events_of_type("message.new")
        self.assertEqual(len(published), 1)
        channels, envelope = published[0]
        self.assertEqual(
            sorted(channels),
            sorted([f"personal:{self.client_user.id}", f"personal:{self.specialist.id}"]),
        )
        self.assertEqual(envelope["data"]["id"], message.id)
        self.assertEqual(envelope["data"]["channelId"], self.chat.channel_id)

        self.chat.refresh_from_db()
        self.assertEqual(self.chat.last_message_id, message.id)
        self.assertEqual(self.chat.last_message_at, message.created_at)
        self.assertEqual(self.member(self.client_user).unread_count, 1)
        self.assertEqual(self.member(self.specialist).unread_count, 0)

    def test_send_is_idempotent_by_client_msg_id(self):
        self.activate_tariff()
        client_msg_id = str(uuid.uuid4())
        first = self.post_message(self.client_user, text="hello", clientMsgId=client_msg_id)
        second = self.post_message(self.client_user, text="hello", clientMsgId=client_msg_id)

        self.assertEqual(first.status_code, 201)
        self.assertEqual(second.status_code, 201)
        self.assertEqual(first.json()["id"], second.json()["id"])
        self.assertEqual(Message.objects.filter(chat=self.chat).count(), 1)
        self.assertEqual(self.send_push_mock.call_count, 1)
        self.assertEqual(len(self.events_of_type("message.new")), 1)
        self.assertEqual(self.member(self.specialist).unread_count, 1)

    def test_client_without_tariff_gets_tariff_required(self):
        response = self.post_message(self.client_user, text="hello")
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["code"], "TARIFF_REQUIRED")
        self.assertFalse(Message.objects.exists())

    def test_empty_message_rejected(self):
        response = self.post_message(self.specialist, text="   ")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["code"], "MESSAGE_EMPTY")
        self.assertFalse(Message.objects.exists())

    def test_reply_to_must_be_same_chat(self):
        other_specialist = User.objects.create_user(username="sp2", password="p", role=ROLE_SPECIALIST)
        other_chat = create_or_get_chat(self.client_user, other_specialist)
        foreign = Message.objects.create(chat=other_chat, sender=other_specialist, text="x")

        response = self.post_message(self.specialist, text="re", replyToId=foreign.id)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["code"], "MESSAGE_NOT_FOUND")

        own = self.make_message(sender=self.client_user, text="question")
        response = self.post_message(self.specialist, text="answer", replyToId=own.id)
        self.assertEqual(response.status_code, 201)
        self.assertEqual(
            response.json()["replyTo"],
            {"id": own.id, "senderId": self.client_user.id, "text": "question", "type": "regular"},
        )

    def test_non_member_gets_404(self):
        stranger = User.objects.create_user(username="stranger", password="p", role=ROLE_CLIENT)
        self.auth(stranger)
        for response in (
            self.client.get(self.messages_url()),
            self.client.post(self.messages_url(), {"text": "x"}, format="json"),
            self.client.post(self.read_url(), {"lastReadMessageId": 1}, format="json"),
        ):
            self.assertEqual(response.status_code, 404)
            self.assertEqual(response.json()["code"], "CHAT_NOT_FOUND")

    def test_new_message_unhides_soft_deleted_chat(self):
        self.activate_tariff()
        now = timezone.now()
        self.chat.deleted_by_specialist_at = now
        self.chat.deleted_by_client_at = now
        self.chat.save(update_fields=["deleted_by_specialist_at", "deleted_by_client_at"])

        response = self.post_message(self.client_user, text="I'm back")
        self.assertEqual(response.status_code, 201)
        self.chat.refresh_from_db()
        self.assertIsNone(self.chat.deleted_by_specialist_at)
        self.assertIsNone(self.chat.deleted_by_client_at)

    def test_unknown_attachment_id_rejected(self):
        response = self.post_message(self.specialist, attachmentIds=[str(uuid.uuid4())])
        self.assertEqual(response.status_code, 400, response.content)
        self.assertEqual(response.json()["code"], "ATTACHMENT_INVALID")

    def test_invalid_payload_rejected(self):
        response = self.post_message(self.specialist, text="x", clientMsgId="not-a-uuid")
        self.assertEqual(response.status_code, 400)


class SystemMessageServiceTests(MessageApiTestCase):
    def test_create_system_message_has_no_unread_and_no_push(self):
        with self.captureOnCommitCallbacks(execute=True):
            message = message_service.create_system_message(
                self.chat, "tariffActivated", "Тариф активирован.", extra_data={"order_id": 1}
            )
        self.assertEqual(message.type, Message.Type.SYSTEM)
        self.assertIsNone(message.sender_id)
        self.assertEqual(message.custom_type, "tariffActivated")
        self.chat.refresh_from_db()
        self.assertEqual(self.chat.last_message_id, message.id)
        self.assertEqual(self.member(self.client_user).unread_count, 0)
        self.assertEqual(self.member(self.specialist).unread_count, 0)
        self.send_push_mock.assert_not_called()
        [(_, envelope)] = self.events_of_type("message.new")
        self.assertEqual(envelope["data"]["customType"], "tariffActivated")
        self.assertIsNone(envelope["data"]["senderId"])


class HistoryTests(MessageApiTestCase):
    def get_history(self, user=None, **params):
        self.auth(user or self.client_user)
        return self.client.get(self.messages_url(), params)

    def test_history_pagination_before_and_after(self):
        base = timezone.now() - timedelta(hours=1)
        created = [
            self.make_message(sender=self.specialist, text=f"m{i}", created_at=base + timedelta(seconds=i))
            for i in range(5)
        ]

        first = self.get_history(limit=2)
        self.assertEqual(first.status_code, 200)
        body = first.json()
        self.assertEqual([m["text"] for m in body["results"]], ["m4", "m3"])
        self.assertTrue(body["hasMore"])

        second = self.get_history(limit=2, before=body["nextCursor"]).json()
        self.assertEqual([m["text"] for m in second["results"]], ["m2", "m1"])
        self.assertTrue(second["hasMore"])

        third = self.get_history(limit=2, before=second["nextCursor"]).json()
        self.assertEqual([m["text"] for m in third["results"]], ["m0"])
        self.assertFalse(third["hasMore"])

        # after: догрузка вперёд от m1, по возрастанию
        after = self.get_history(limit=2, after=second["nextCursor"]).json()
        self.assertEqual([m["text"] for m in after["results"]], ["m2", "m3"])
        self.assertTrue(after["hasMore"])
        tail = self.get_history(limit=2, after=after["nextCursor"]).json()
        self.assertEqual([m["text"] for m in tail["results"]], ["m4"])
        self.assertFalse(tail["hasMore"])
        self.assertEqual(len(created), 5)

    def test_history_orders_by_created_at_not_id(self):
        now = timezone.now()
        later = self.make_message(sender=self.specialist, text="later", created_at=now)
        # бóльший id, но более раннее время (как у импортированного сообщения)
        earlier = self.make_message(sender=self.specialist, text="earlier", created_at=now - timedelta(minutes=5))
        self.assertGreater(earlier.id, later.id)

        desc = self.get_history().json()
        self.assertEqual([m["text"] for m in desc["results"]], ["later", "earlier"])

        cursor = desc["nextCursor"]  # курсор последнего элемента = earlier
        newer = self.get_history(after=cursor).json()
        self.assertEqual([m["text"] for m in newer["results"]], ["later"])

    def test_history_same_created_at_uses_id_as_tiebreaker(self):
        now = timezone.now()
        first = self.make_message(sender=self.specialist, text="a", created_at=now)
        second = self.make_message(sender=self.specialist, text="b", created_at=now)
        page = self.get_history(limit=1).json()
        self.assertEqual(page["results"][0]["id"], second.id)
        rest = self.get_history(limit=1, before=page["nextCursor"]).json()
        self.assertEqual(rest["results"][0]["id"], first.id)
        self.assertFalse(rest["hasMore"])

    def test_after_cursor_built_from_message_json(self):
        # контракт MESSENGER_API.md: курсор = base64url("<createdAt>|<id>") без '=' из JSON сообщения
        # (например, полученного по realtime) — так клиент догружает пропущенное после переподключения
        base = timezone.now() - timedelta(minutes=1)
        for i in range(3):
            self.make_message(sender=self.specialist, text=f"m{i}", created_at=base + timedelta(seconds=i))
        known = self.get_history(limit=1).json()["results"][0]  # m2 — последнее известное клиенту
        self.make_message(sender=self.specialist, text="new", created_at=base + timedelta(seconds=10))

        page = self.get_history().json()
        m1 = next(m for m in page["results"] if m["text"] == "m1")
        cursor = base64.urlsafe_b64encode(f"{m1['createdAt']}|{m1['id']}".encode()).decode().rstrip("=")
        newer = self.get_history(after=cursor).json()
        self.assertEqual([m["text"] for m in newer["results"]], ["m2", "new"])

        cursor = base64.urlsafe_b64encode(f"{known['createdAt']}|{known['id']}".encode()).decode().rstrip("=")
        self.assertEqual([m["text"] for m in self.get_history(after=cursor).json()["results"]], ["new"])

    def test_invalid_cursor_and_limit(self):
        for params in (
            {"before": "garbage!!"},
            {"after": base64.urlsafe_b64encode(b"nope").decode()},
            {"before": "x", "after": "y"},
            {"limit": "abc"},
            {"limit": "0"},
        ):
            response = self.get_history(**params)
            self.assertEqual(response.status_code, 400, params)
            self.assertEqual(response.json()["code"], "PARAM_INVALID", params)

    def test_limit_is_capped_at_100(self):
        now = timezone.now()
        Message.objects.bulk_create(
            Message(chat=self.chat, sender=self.specialist, text=str(i), created_at=now - timedelta(seconds=i))
            for i in range(105)
        )
        body = self.get_history(limit=500).json()
        self.assertEqual(len(body["results"]), 100)
        self.assertTrue(body["hasMore"])

    def test_history_without_tariff_is_visible(self):
        self.make_message(sender=self.specialist, text="hello")
        response = self.get_history(self.client_user)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()["results"]), 1)


class EditDeleteTests(MessageApiTestCase):
    def patch_message(self, user, message, text):
        self.auth(user)
        with self.captureOnCommitCallbacks(execute=True):
            return self.client.patch(self.message_url(message), {"text": text}, format="json")

    def delete_message(self, user, message):
        self.auth(user)
        with self.captureOnCommitCallbacks(execute=True):
            return self.client.delete(self.message_url(message))

    def test_edit_own_message(self):
        message = self.make_message(sender=self.client_user, text="old")
        # редактирование не требует тарифа
        response = self.patch_message(self.client_user, message, " new ")
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["text"], "new")
        self.assertIsNotNone(response.json()["editedAt"])
        message.refresh_from_db()
        self.assertEqual(message.text, "new")
        self.assertIsNotNone(message.edited_at)
        [(channels, envelope)] = self.events_of_type("message.updated")
        self.assertEqual(len(channels), 2)
        self.assertEqual(envelope["data"]["text"], "new")

    def test_edit_to_empty_rejected(self):
        message = self.make_message(sender=self.client_user, text="old")
        response = self.patch_message(self.client_user, message, "  ")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["code"], "MESSAGE_EMPTY")

    def test_cannot_edit_others_or_system(self):
        foreign = self.make_message(sender=self.specialist, text="theirs")
        system = self.make_message(sender=None, text="sys", type=Message.Type.SYSTEM, custom_type="tariffActivated")
        for message in (foreign, system):
            response = self.patch_message(self.client_user, message, "hacked")
            self.assertEqual(response.status_code, 403)
            self.assertEqual(response.json()["code"], "MESSAGE_EDIT_FORBIDDEN")
            response = self.delete_message(self.client_user, message)
            self.assertEqual(response.status_code, 403)
            self.assertEqual(response.json()["code"], "MESSAGE_EDIT_FORBIDDEN")
        self.assertEqual(self.events_of_type("message.updated"), [])

    def test_edit_unknown_message_404(self):
        self.auth(self.client_user)
        response = self.client.patch(f"{self.messages_url()}999999/", {"text": "x"}, format="json")
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["code"], "MESSAGE_NOT_FOUND")

    def test_delete_hides_text_and_publishes_updated(self):
        message = self.make_message(sender=self.client_user, text="secret")
        reply = self.make_message(sender=self.specialist, text="re", reply_to=message)

        response = self.delete_message(self.client_user, message)
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["text"], "")
        self.assertIsNotNone(response.json()["deletedAt"])
        message.refresh_from_db()
        self.assertIsNotNone(message.deleted_at)
        [(_, envelope)] = self.events_of_type("message.updated")
        self.assertEqual(envelope["data"]["text"], "")
        self.assertIsNotNone(envelope["data"]["deletedAt"])

        history = self.client.get(self.messages_url()).json()["results"]
        by_id = {m["id"]: m for m in history}
        self.assertEqual(by_id[message.id]["text"], "")
        self.assertEqual(by_id[reply.id]["replyTo"]["text"], "")

        # удалённое нельзя редактировать
        response = self.patch_message(self.client_user, message, "again")
        self.assertEqual(response.status_code, 403)


class ReadStateTests(MessageApiTestCase):
    def mark_read(self, user, message_id):
        self.auth(user)
        with self.captureOnCommitCallbacks(execute=True):
            return self.client.post(self.read_url(), {"lastReadMessageId": message_id}, format="json")

    def test_mark_read_is_monotonic_and_resets_unread(self):
        for text in ("a", "b", "c"):
            response = self.post_message(self.specialist, text=text)
            self.assertEqual(response.status_code, 201)
        msgs = list(Message.objects.filter(chat=self.chat).order_by("created_at", "id"))
        self.assertEqual(self.member(self.client_user).unread_count, 3)
        self.broadcast_mock.reset_mock()

        response = self.mark_read(self.client_user, msgs[1].id)
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["unreadCount"], 1)
        member = self.member(self.client_user)
        self.assertEqual(member.last_read_message_id, msgs[1].id)
        self.assertEqual(member.unread_count, 1)
        [(channels, envelope)] = self.events_of_type("chat.read")
        self.assertEqual(
            sorted(channels),
            sorted([f"personal:{self.client_user.id}", f"personal:{self.specialist.id}"]),
        )
        self.assertEqual(
            envelope["data"],
            {"channelId": self.chat.channel_id, "userId": self.client_user.id, "lastReadMessageId": msgs[1].id},
        )

        # более раннее сообщение игнорируется
        self.broadcast_mock.reset_mock()
        response = self.mark_read(self.client_user, msgs[0].id)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["lastReadMessageId"], msgs[1].id)
        self.assertEqual(self.member(self.client_user).last_read_message_id, msgs[1].id)
        self.assertEqual(self.events_of_type("chat.read"), [])

        response = self.mark_read(self.client_user, msgs[2].id)
        self.assertEqual(response.json()["unreadCount"], 0)
        self.assertEqual(self.member(self.client_user).unread_count, 0)

    def test_mark_read_counts_by_created_at(self):
        now = timezone.now()
        read_target = self.make_message(sender=self.specialist, text="read", created_at=now)
        # импортированное сообщение: больший id, но раньше по времени — уже «прочитано»
        self.make_message(sender=self.specialist, text="old import", created_at=now - timedelta(minutes=1))
        self.make_message(sender=self.specialist, text="new", created_at=now + timedelta(seconds=1))
        self.make_message(sender=self.client_user, text="own", created_at=now + timedelta(seconds=2))
        response = self.mark_read(self.client_user, read_target.id)
        self.assertEqual(response.json()["unreadCount"], 1)

    def test_mark_read_unknown_message(self):
        response = self.mark_read(self.client_user, 999999)
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["code"], "MESSAGE_NOT_FOUND")

    def test_mark_read_requires_message_id(self):
        self.auth(self.client_user)
        response = self.client.post(self.read_url(), {}, format="json")
        self.assertEqual(response.status_code, 400)


class MarkUnreadTests(MessageApiTestCase):
    def unread_url(self, chat=None):
        return f"/api/chats/{(chat or self.chat).channel_id}/unread/"

    def mark_unread(self, user, message_id, chat=None):
        self.auth(user)
        with self.captureOnCommitCallbacks(execute=True):
            return self.client.post(self.unread_url(chat), {"messageId": message_id}, format="json")

    def setUp(self):
        super().setUp()
        now = timezone.now()
        self.m1 = self.make_message(sender=self.specialist, text="1", created_at=now)
        self.m2 = self.make_message(sender=self.client_user, text="2", created_at=now + timedelta(seconds=1))
        self.m3 = self.make_message(sender=self.specialist, text="3", created_at=now + timedelta(seconds=2))
        self.m4 = self.make_message(sender=self.specialist, text="4", created_at=now + timedelta(seconds=3))
        ChatMember.objects.filter(chat=self.chat, user=self.client_user).update(
            last_read_message_id=self.m4.id, unread_count=0
        )
        ChatMember.objects.filter(chat=self.chat, user=self.specialist).update(
            last_read_message_id=self.m4.id, unread_count=0
        )

    def test_mark_unread_moves_read_position_back_and_notifies_only_self(self):
        response = self.mark_unread(self.client_user, self.m3.id)

        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(
            response.json(),
            {"channelId": self.chat.channel_id, "lastReadMessageId": self.m2.id, "unreadCount": 2},
        )
        member = self.member(self.client_user)
        self.assertEqual(member.last_read_message_id, self.m2.id)
        self.assertEqual(member.unread_count, 2)  # m3, m4 от специалиста
        [(channels, envelope)] = self.events_of_type("chat.unread")
        self.assertEqual(channels, [f"personal:{self.client_user.id}"])
        self.assertEqual(
            envelope["data"],
            {"channelId": self.chat.channel_id, "lastReadMessageId": self.m2.id, "unreadCount": 2},
        )
        self.assertEqual(self.events_of_type("chat.read"), [])
        # у собеседника своя позиция не меняется
        self.assertEqual(self.member(self.specialist).last_read_message_id, self.m4.id)

    def test_mark_unread_uses_created_at_order_not_id(self):
        # импортированное сообщение: больший id, но раньше m3 по времени — станет «прочитанным до»
        imported = self.make_message(
            sender=self.specialist, text="imported", created_at=self.m3.created_at - timedelta(milliseconds=500)
        )
        response = self.mark_unread(self.client_user, self.m3.id)
        self.assertEqual(response.json()["lastReadMessageId"], imported.id)
        self.assertEqual(response.json()["unreadCount"], 2)

    def test_mark_unread_first_message_resets_to_null(self):
        response = self.mark_unread(self.client_user, self.m1.id)
        self.assertEqual(response.status_code, 200, response.content)
        self.assertIsNone(response.json()["lastReadMessageId"])
        self.assertEqual(response.json()["unreadCount"], 3)
        self.assertIsNone(self.member(self.client_user).last_read_message_id)

    def test_mark_read_after_unread_moves_forward_again(self):
        self.mark_unread(self.client_user, self.m3.id)
        self.auth(self.client_user)
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(
                f"/api/chats/{self.chat.channel_id}/read/", {"lastReadMessageId": self.m3.id}, format="json"
            )
        self.assertEqual(response.json()["lastReadMessageId"], self.m3.id)
        self.assertEqual(response.json()["unreadCount"], 1)

    def test_mark_unread_works_without_tariff(self):
        # у клиента нет активного тарифа (setUp не активирует) — отметка всё равно работает
        response = self.mark_unread(self.client_user, self.m3.id)
        self.assertEqual(response.status_code, 200)

    def test_mark_unread_unknown_or_foreign_message_404(self):
        other_specialist = User.objects.create_user(username="sp_unread", password="p", role=ROLE_SPECIALIST)
        other_chat = create_or_get_chat(self.client_user, other_specialist)
        foreign = Message.objects.create(chat=other_chat, sender=other_specialist, text="x")
        for message_id in (999999, foreign.id):
            response = self.mark_unread(self.client_user, message_id)
            self.assertEqual(response.status_code, 404, message_id)
            self.assertEqual(response.json()["code"], "MESSAGE_NOT_FOUND")
        self.assertEqual(self.member(self.client_user).last_read_message_id, self.m4.id)

    def test_mark_unread_deleted_message_404(self):
        self.m3.deleted_at = timezone.now()
        self.m3.save(update_fields=["deleted_at"])
        response = self.mark_unread(self.client_user, self.m3.id)
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["code"], "MESSAGE_NOT_FOUND")

    def test_mark_unread_requires_message_id_and_membership(self):
        self.auth(self.client_user)
        response = self.client.post(self.unread_url(), {}, format="json")
        self.assertEqual(response.status_code, 400)

        stranger = User.objects.create_user(username="stranger_unread", password="p", role=ROLE_CLIENT)
        response = self.mark_unread(stranger, self.m3.id)
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["code"], "CHAT_NOT_FOUND")

    def test_mark_unread_after_current_position_is_noop(self):
        ChatMember.objects.filter(chat=self.chat, user=self.client_user).update(
            last_read_message_id=self.m2.id, unread_count=2
        )
        # m4: «до него» — m3, это дальше текущей позиции m2 → ничего не меняем
        for target in (self.m4, self.m3):
            self.broadcast_mock.reset_mock()
            response = self.mark_unread(self.client_user, target.id)
            self.assertEqual(response.status_code, 200, response.content)
            self.assertEqual(
                response.json(),
                {"channelId": self.chat.channel_id, "lastReadMessageId": self.m2.id, "unreadCount": 2},
            )
            self.assertEqual(self.events_of_type("chat.unread"), [])
        member = self.member(self.client_user)
        self.assertEqual(member.last_read_message_id, self.m2.id)
        self.assertIsNone(member.read_changed_at)

    def test_mark_unread_when_nothing_read_is_noop(self):
        ChatMember.objects.filter(chat=self.chat, user=self.client_user).update(
            last_read_message_id=None, unread_count=3
        )
        response = self.mark_unread(self.client_user, self.m3.id)
        self.assertEqual(response.json()["lastReadMessageId"], None)
        self.assertEqual(response.json()["unreadCount"], 3)
        self.assertEqual(self.events_of_type("chat.unread"), [])

    def test_mark_unread_equal_created_at_id_decides(self):
        same = self.m4.created_at + timedelta(seconds=1)
        first = self.make_message(sender=self.specialist, text="a", created_at=same)
        second = self.make_message(sender=self.specialist, text="b", created_at=same)
        ChatMember.objects.filter(chat=self.chat, user=self.client_user).update(last_read_message_id=second.id)

        response = self.mark_unread(self.client_user, second.id)
        self.assertEqual(response.json()["lastReadMessageId"], first.id)
        self.assertEqual(response.json()["unreadCount"], 1)

        response = self.mark_unread(self.client_user, first.id)
        self.assertEqual(response.json()["lastReadMessageId"], self.m4.id)
        self.assertEqual(response.json()["unreadCount"], 2)

    def test_mark_unread_on_own_message_gives_zero_unread(self):
        own_1 = self.make_message(sender=self.client_user, text="own1", created_at=self.m4.created_at + timedelta(seconds=1))
        own_2 = self.make_message(sender=self.client_user, text="own2", created_at=self.m4.created_at + timedelta(seconds=2))
        ChatMember.objects.filter(chat=self.chat, user=self.client_user).update(last_read_message_id=own_2.id)

        response = self.mark_unread(self.client_user, own_1.id)

        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["lastReadMessageId"], self.m4.id)
        self.assertEqual(response.json()["unreadCount"], 0)
        self.assertEqual(len(self.events_of_type("chat.unread")), 1)

    def test_read_and_unread_stamp_read_changed_at(self):
        self.assertIsNone(self.member(self.client_user).read_changed_at)
        self.mark_unread(self.client_user, self.m3.id)
        unread_stamp = self.member(self.client_user).read_changed_at
        self.assertIsNotNone(unread_stamp)

        self.auth(self.client_user)
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(f"/api/chats/{self.chat.channel_id}/read/", {"lastReadMessageId": self.m4.id}, format="json")
        self.assertGreater(self.member(self.client_user).read_changed_at, unread_stamp)

        # отправка своего сообщения позицию «прочитано» не трогает
        self.assertIsNone(self.member(self.specialist).read_changed_at)
        message_service.send_message(self.chat, self.specialist, text="hi")
        self.assertIsNone(self.member(self.specialist).read_changed_at)

    def test_companion_sees_new_position_in_rest(self):
        self.mark_unread(self.client_user, self.m3.id)
        self.auth(self.specialist)
        body = self.client.get(f"/api/chats/{self.chat.channel_id}/").json()
        self.assertEqual(body["lastReadMessageId"], self.m4.id)
        self.assertEqual(body["companionLastReadMessageId"], self.m2.id)


class MessagePushTests(MessageApiTestCase):
    def test_push_sent_to_recipient_with_thread_id(self):
        self.specialist.first_name = "Анна"
        self.specialist.last_name = "Петрова"
        self.specialist.save(update_fields=["first_name", "last_name"])
        response = self.post_message(self.specialist, text="Добрый день")
        message_id = response.json()["id"]

        self.send_push_mock.assert_called_once()
        kwargs = self.send_push_mock.call_args.kwargs
        recipient = kwargs.get("user") or self.send_push_mock.call_args.args[0]
        self.assertEqual(recipient, self.client_user)
        self.assertEqual(kwargs["title"], "Анна Петрова")
        self.assertEqual(kwargs["message"], "Добрый день")
        self.assertEqual(kwargs["thread_id"], self.chat.channel_id)
        self.assertEqual(
            kwargs["extra"],
            {
                "type": "chat_message",
                "channelId": self.chat.channel_id,
                "messageId": message_id,
                "senderId": self.specialist.id,
                "senderName": "Анна Петрова",
            },
        )

    def test_push_skipped_when_recipient_muted(self):
        self.activate_tariff()
        self.auth(self.specialist)
        with patch("chat_access.views.chat.sync_blocked_by_to_stream"), \
                patch("chat_access.views.chat.mute_user_for_user"):
            response = self.client.post(
                "/api/chats/blacklist/add/", {"channelId": self.chat.channel_id}, format="json"
            )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(self.member(self.specialist).muted)

        response = self.post_message(self.client_user, text="ping")
        self.assertEqual(response.status_code, 201)
        self.send_push_mock.assert_not_called()

        with patch("chat_access.views.chat.sync_blocked_by_to_stream"), \
                patch("chat_access.views.chat.unmute_user_for_user"):
            self.auth(self.specialist)
            self.client.post("/api/chats/blacklist/remove/", {"channelId": self.chat.channel_id}, format="json")
        self.assertFalse(self.member(self.specialist).muted)

    def test_push_fallback_texts(self):
        from messenger.services import push

        message = self.make_message(sender=self.specialist, text="")
        self.assertEqual(push.message_preview(message), "Сообщение")
        self.assertEqual(push.sender_display_name(self.specialist), "specialist_1")


class SendPushThreadIdTests(MessengerTestCase):
    def _send(self, **kwargs):
        from common.notifications import send_push

        device = GCMDevice.objects.create(user=self.client_user, registration_id="tok", cloud_message_type="FCM")
        response = MagicMock(success_count=1)
        with patch.object(GCMDevice, "send_message", return_value=response) as send_message:
            self.assertTrue(send_push(self.client_user, "t", "m", **kwargs))
        self.assertTrue(device.pk)
        return send_message.call_args.args[0]

    def test_thread_id_sets_android_tag_and_apns_thread(self):
        firebase_message = self._send(thread_id="chat_1_2")
        self.assertEqual(firebase_message.android.notification.tag, "chat_1_2")
        self.assertEqual(firebase_message.apns.payload.aps.thread_id, "chat_1_2")

    def test_without_thread_id_behaviour_unchanged(self):
        firebase_message = self._send()
        self.assertIsNone(firebase_message.android.notification.tag)
        self.assertIsNone(firebase_message.apns.payload.aps.thread_id)


class PublishHardeningTests(MessengerTestCase):
    def test_non_centrifugo_error_is_logged_and_swallowed(self):
        self.broadcast_mock.side_effect = TypeError("Object of type datetime is not JSON serializable")
        with patch("messenger.tasks.publish_event.apply_async") as apply_async:
            with self.assertLogs("messenger.services.events", level="ERROR"):
                with self.captureOnCommitCallbacks(execute=True):
                    events.publish([1], "message.new", {"channel_id": "c"})
        apply_async.assert_not_called()


class IdempotentResendTests(MessageApiTestCase):
    def test_resend_after_tariff_expiry_returns_existing_message(self):
        order = self.activate_tariff()
        client_msg_id = str(uuid.uuid4())
        first = self.post_message(self.client_user, text="hello", clientMsgId=client_msg_id)
        self.assertEqual(first.status_code, 201)
        pushes = self.send_push_mock.call_count
        published = len(self.events_of_type("message.new"))

        order.expires_at = timezone.now() - timedelta(minutes=1)
        order.save(update_fields=["expires_at"])

        second = self.post_message(self.client_user, text="hello", clientMsgId=client_msg_id)
        self.assertEqual(second.status_code, 201, second.content)
        self.assertEqual(second.json()["id"], first.json()["id"])
        self.assertEqual(self.send_push_mock.call_count, pushes)
        self.assertEqual(len(self.events_of_type("message.new")), published)

        # новое сообщение без тарифа по-прежнему запрещено
        third = self.post_message(self.client_user, text="new", clientMsgId=str(uuid.uuid4()))
        self.assertEqual(third.status_code, 403)
        self.assertEqual(third.json()["code"], "TARIFF_REQUIRED")

    def test_insert_race_falls_back_to_existing_message(self):
        client_msg_id = uuid.uuid4()
        with self.captureOnCommitCallbacks(execute=True):
            existing = message_service.send_message(
                self.chat, self.specialist, text="hello", client_msg_id=client_msg_id
            )
        real_lookup = message_service._find_by_client_msg_id
        # первая проверка «не видит» сообщение — вставка упирается в уникальный индекс
        with patch.object(
            message_service, "_find_by_client_msg_id", side_effect=[None, real_lookup(self.chat, self.specialist, client_msg_id)]
        ) as lookup:
            with self.captureOnCommitCallbacks(execute=True):
                result = message_service.send_message(
                    self.chat, self.specialist, text="hello", client_msg_id=client_msg_id
                )

        self.assertEqual(lookup.call_count, 2)
        self.assertEqual(result.pk, existing.pk)
        self.assertEqual(Message.objects.filter(chat=self.chat).count(), 1)
        self.assertEqual(len(self.events_of_type("message.new")), 1)
