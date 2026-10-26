from django.apps import apps as django_apps
from django.db import IntegrityError, transaction

from chat_access.models import Chat
from chat_access.services.chat_commands import create_or_get_chat
from messenger.models import Call, ChatMember, Message
from messenger.services import ensure_members
from messenger.tests.base import MessengerTestCase


class EnsureMembersTests(MessengerTestCase):
    def test_ensure_members_creates_two_rows_idempotently(self):
        ChatMember.objects.filter(chat=self.chat).delete()

        ensure_members(self.chat)
        ensure_members(self.chat)

        members = ChatMember.objects.filter(chat=self.chat)
        self.assertEqual(members.count(), 2)
        self.assertEqual(members.get(user=self.client_user).role, "client")
        self.assertEqual(members.get(user=self.specialist).role, "specialist")

    def test_create_or_get_chat_creates_members(self):
        self.assertEqual(ChatMember.objects.filter(chat=self.chat).count(), 2)

    def test_create_or_get_chat_existing_restores_missing_members(self):
        ChatMember.objects.filter(chat=self.chat).delete()
        create_or_get_chat(self.client_user, self.specialist)
        self.assertEqual(ChatMember.objects.filter(chat=self.chat).count(), 2)

    def test_member_for(self):
        member = self.chat.member_for(self.client_user)
        self.assertEqual(member.role, ChatMember.Role.CLIENT)
        self.assertEqual(member.unread_count, 0)
        self.assertFalse(member.muted)
        self.assertIsNone(self.chat.member_for(self.specialist.__class__.objects.create_user(
            username="stranger", password="pass",
        )))


class BackfillMigrationTests(MessengerTestCase):
    def test_backfill_migration_creates_members_for_existing_chats(self):
        from importlib import import_module

        backfill = import_module("messenger.migrations.0002_backfill_members").backfill

        ChatMember.objects.all().delete()
        backfill(django_apps, None)
        backfill(django_apps, None)  # идемпотентность

        self.assertEqual(ChatMember.objects.filter(chat=self.chat).count(), 2)
        self.assertEqual(
            set(ChatMember.objects.filter(chat=self.chat).values_list("role", flat=True)),
            {"client", "specialist"},
        )


class MessageModelTests(MessengerTestCase):
    def test_client_msg_id_unique_per_chat_and_sender(self):
        import uuid

        cid = uuid.uuid4()
        Message.objects.create(chat=self.chat, sender=self.client_user, text="a", client_msg_id=cid)
        with self.assertRaises(IntegrityError), transaction.atomic():
            Message.objects.create(chat=self.chat, sender=self.client_user, text="b", client_msg_id=cid)
        # другой отправитель — можно, и без client_msg_id — сколько угодно
        Message.objects.create(chat=self.chat, sender=self.specialist, text="c", client_msg_id=cid)
        Message.objects.create(chat=self.chat, sender=self.client_user, text="d")
        Message.objects.create(chat=self.chat, sender=self.client_user, text="e")

    def test_chat_last_message_fields(self):
        message = Message.objects.create(chat=self.chat, sender=self.client_user, text="hi")
        Chat.objects.filter(pk=self.chat.pk).update(last_message=message, last_message_at=message.created_at)
        self.chat.refresh_from_db()
        self.assertEqual(self.chat.last_message_id, message.id)

    def test_enums(self):
        self.assertEqual(Call.ACTIVE_STATUSES, (Call.Status.RINGING, Call.Status.ACCEPTED))
        self.assertEqual(Message.Type.CALL, "call")
