from datetime import timedelta

from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from messenger.models import Attachment, Message
from messenger.tests.test_attachments import AttachmentTestCase


class ReplyToTests(AttachmentTestCase):
    """`replyTo`: время, удаление и краткое первое вложение исходного сообщения."""

    def make_message(self, sender=None, text="hi", created_at=None, **extra):
        return Message.objects.create(
            chat=self.chat, sender=sender, text=text, created_at=created_at or timezone.now(), **extra
        )

    def history(self, user=None):
        self.auth(user or self.client_user)
        response = self.client.get(self.messages_url())
        self.assertEqual(response.status_code, 200, response.content)
        return response.json()["results"]

    def test_reply_to_has_created_at_deleted_at_and_first_attachment(self):
        original = self.make_message(sender=self.specialist, text="Вопрос")
        # порядок вложений — по position, а не по времени создания
        second = self.make_attachment(message=original, position=1, file_name="b.png", status="ready")
        first = self.make_attachment(
            message=original, position=0, kind=Attachment.Kind.FILE, file_name="a.pdf", status="ready"
        )
        self.assertNotEqual(first.pk, second.pk)
        self.make_message(sender=self.client_user, text="Ответ", reply_to=original)

        reply = next(m for m in self.history() if m["text"] == "Ответ")
        reply_to = reply["replyTo"]
        self.assertEqual(reply_to["id"], original.id)
        self.assertEqual(reply_to["text"], "Вопрос")
        self.assertIsNone(reply_to["deletedAt"])
        self.assertIsNotNone(reply_to["createdAt"])
        self.assertEqual(
            reply_to["attachment"],
            {
                "id": str(first.pk),
                "kind": "file",
                "fileName": "a.pdf",
                "url": f"https://files.example.com/get/{first.object_key}",
            },
        )

    def test_reply_to_without_attachments_has_null_attachment(self):
        original = self.make_message(sender=self.specialist, text="Вопрос")
        self.make_message(sender=self.client_user, text="Ответ", reply_to=original)
        reply = next(m for m in self.history() if m["text"] == "Ответ")
        self.assertIsNone(reply["replyTo"]["attachment"])

    def test_reply_to_deleted_message_hides_text_and_attachment(self):
        original = self.make_message(sender=self.specialist, text="Вопрос", deleted_at=timezone.now())
        self.make_attachment(message=original, position=0, status="ready")
        self.make_message(sender=self.client_user, text="Ответ", reply_to=original)
        reply_to = next(m for m in self.history() if m["text"] == "Ответ")["replyTo"]
        self.assertEqual(reply_to["text"], "")
        self.assertIsNotNone(reply_to["deletedAt"])
        self.assertIsNone(reply_to["attachment"])

    def test_deleted_reply_has_null_reply_to(self):
        original = self.make_message(sender=self.specialist, text="Вопрос")
        self.make_attachment(message=original, position=0, status="ready")
        self.make_message(sender=self.client_user, text="Ответ", reply_to=original, deleted_at=timezone.now())
        deleted = next(m for m in self.history() if m["deletedAt"] is not None)
        self.assertIsNone(deleted["replyTo"])

    def test_send_reply_returns_rich_reply_to(self):
        original = self.make_message(sender=self.specialist, text="Вопрос")
        self.make_attachment(message=original, position=0, status="ready")
        response = self.send(self.specialist, text="Ответ", replyToId=original.id)
        self.assertEqual(response.status_code, 201, response.content)
        reply_to = response.json()["replyTo"]
        self.assertEqual(reply_to["attachment"]["kind"], "image")
        self.assertIn("createdAt", reply_to)

    def test_history_with_replies_has_no_n_plus_one(self):
        def history_queries():
            self.auth(self.client_user)
            with CaptureQueriesContext(connection) as ctx:
                self.client.get(self.messages_url())
            return [q["sql"] for q in ctx.captured_queries if "silk_" not in q["sql"]]

        base = timezone.now() - timedelta(minutes=10)
        original = self.make_message(sender=self.specialist, text="q0", created_at=base)
        self.make_attachment(message=original, position=0, status="ready")
        self.make_message(sender=self.client_user, text="r0", reply_to=original, created_at=base + timedelta(seconds=1))
        baseline = len(history_queries())

        for i in range(1, 4):
            original = self.make_message(sender=self.specialist, text=f"q{i}", created_at=base + timedelta(seconds=10 * i))
            self.make_attachment(message=original, position=0, status="ready")
            self.make_message(
                sender=self.client_user, text=f"r{i}", reply_to=original,
                created_at=base + timedelta(seconds=10 * i + 1),
            )
        self.assertEqual(len(history_queries()), baseline)
