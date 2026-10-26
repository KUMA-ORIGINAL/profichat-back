import uuid
from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import SimpleTestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from account.models import ROLE_CLIENT, ROLE_SPECIALIST
from chat_access.services.chat_commands import create_or_get_chat
from messenger import tasks
from messenger.clients import storage
from messenger.models import Attachment, Message
from messenger.tests.base import MessengerTestCase

User = get_user_model()
MB = 1024 * 1024


class StorageClientTests(SimpleTestCase):
    @override_settings(
        S3_ENDPOINT_URL="http://minio:9000",
        S3_PUBLIC_ENDPOINT_URL="https://files.example.com",
        S3_ACCESS_KEY="key",
        S3_SECRET_KEY="secret",
        S3_BUCKET="messenger",
        S3_REGION="us-east-1",
    )
    def test_presigned_urls_use_public_host_and_path_style(self):
        put_url = storage.presigned_put("chats/1/abc/a.png", "image/png", 900)
        get_url = storage.presigned_get("chats/1/abc/a.png", 3600, "тест файл.png")

        self.assertTrue(put_url.startswith("https://files.example.com/messenger/chats/1/abc/a.png?"), put_url)
        self.assertIn("X-Amz-Signature=", put_url)
        self.assertIn("X-Amz-Expires=900", put_url)
        self.assertTrue(get_url.startswith("https://files.example.com/messenger/chats/1/abc/a.png?"), get_url)
        self.assertIn("X-Amz-Expires=3600", get_url)
        self.assertIn("response-content-disposition=", get_url)
        self.assertIn("UTF-8", get_url)

    def test_safe_file_name(self):
        self.assertEqual(storage.safe_file_name("../../etc/pa ss?wd.txt"), "pa_ss_wd.txt")
        self.assertEqual(storage.safe_file_name(""), "file")
        self.assertEqual(storage.safe_file_name("фото.jpg"), "фото.jpg")
        long_name = storage.safe_file_name("a" * 500 + ".png")
        self.assertLessEqual(len(long_name), 100)
        self.assertTrue(long_name.endswith(".png"))


def app_queries(ctx):
    """Запросы приложения к БД (без служебных запросов silk при DEBUG)."""
    return [q["sql"] for q in ctx.captured_queries if q["sql"].startswith("SELECT") and "silk_" not in q["sql"]]


class AttachmentTestCase(MessengerTestCase):
    def setUp(self):
        super().setUp()
        for name, kwargs in (
            ("presigned_put", {"return_value": "https://files.example.com/put?sig=1"}),
            ("presigned_get", {"side_effect": lambda key, expires, file_name: f"https://files.example.com/get/{key}"}),
            ("head", {"return_value": {"ContentLength": 1024}}),
            ("delete", {}),
        ):
            patcher = patch(f"messenger.clients.storage.{name}", **kwargs)
            setattr(self, f"storage_{name}", patcher.start())
            self.addCleanup(patcher.stop)
        push_patcher = patch("messenger.services.push.send_push")
        push_patcher.start()
        self.addCleanup(push_patcher.stop)

    def upload_url(self, chat=None):
        return f"/api/chats/{(chat or self.chat).channel_id}/attachments/"

    def messages_url(self, chat=None):
        return f"/api/chats/{(chat or self.chat).channel_id}/messages/"

    def upload_payload(self, **overrides):
        payload = {"kind": "image", "fileName": "photo.png", "mimeType": "image/png", "size": 1024}
        payload.update(overrides)
        return payload

    def request_upload(self, user, chat=None, **overrides):
        self.auth(user)
        return self.client.post(self.upload_url(chat), self.upload_payload(**overrides), format="json")

    def make_attachment(self, uploader=None, chat=None, **extra):
        chat = chat or self.chat
        attachment_id = extra.pop("id", None) or uuid.uuid4()
        defaults = dict(
            id=attachment_id,
            uploader=uploader or self.specialist,
            chat=chat,
            kind=Attachment.Kind.IMAGE,
            object_key=f"chats/{chat.pk}/{attachment_id}/photo.png",
            file_name="photo.png",
            mime_type="image/png",
            size=1024,
        )
        defaults.update(extra)
        return Attachment.objects.create(**defaults)

    def send(self, user, **payload):
        self.auth(user)
        with self.captureOnCommitCallbacks(execute=True):
            return self.client.post(self.messages_url(), payload, format="json")

    def enable_voice(self, enabled=True):
        self.chat.client_can_send_voice = enabled
        self.chat.save(update_fields=["client_can_send_voice"])


class CreateUploadTests(AttachmentTestCase):
    def test_create_upload_returns_presigned_url(self):
        response = self.request_upload(self.specialist, width=640, height=480)

        self.assertEqual(response.status_code, 201, response.content)
        body = response.json()
        self.assertEqual(set(body), {"id", "uploadUrl", "uploadHeaders", "expiresAt"})
        self.assertEqual(body["uploadUrl"], "https://files.example.com/put?sig=1")
        self.assertEqual(body["uploadHeaders"], {"Content-Type": "image/png"})

        attachment = Attachment.objects.get(pk=body["id"])
        self.assertEqual(attachment.status, Attachment.Status.PENDING)
        self.assertIsNone(attachment.message_id)
        self.assertEqual(attachment.uploader, self.specialist)
        self.assertEqual(attachment.chat, self.chat)
        self.assertEqual((attachment.width, attachment.height), (640, 480))
        self.assertEqual(attachment.object_key, f"chats/{self.chat.pk}/{attachment.pk}/photo.png")

        self.storage_presigned_put.assert_called_once_with(attachment.object_key, "image/png", 15 * 60)

    def test_object_key_is_sanitized(self):
        response = self.request_upload(self.specialist, fileName="../../my photo?.png")
        self.assertEqual(response.status_code, 201, response.content)
        attachment = Attachment.objects.get(pk=response.json()["id"])
        self.assertEqual(attachment.object_key, f"chats/{self.chat.pk}/{attachment.pk}/my_photo_.png")
        self.assertEqual(attachment.file_name, "../../my photo?.png")

    def test_voice_upload_forbidden_when_disabled(self):
        self.activate_tariff()
        self.enable_voice(False)

        response = self.request_upload(
            self.client_user, kind="voice", mimeType="audio/aac", fileName="v.aac", durationMs=3000, waveform=[1, 2, 3]
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["code"], "VOICE_NOT_ALLOWED")
        self.assertFalse(Attachment.objects.exists())

    def test_voice_upload_allowed_for_client_when_enabled(self):
        self.activate_tariff()
        self.enable_voice(True)

        response = self.request_upload(
            self.client_user, kind="voice", mimeType="audio/aac", fileName="v.aac", durationMs=3000, waveform=[1, 2, 3]
        )
        self.assertEqual(response.status_code, 201, response.content)
        attachment = Attachment.objects.get(pk=response.json()["id"])
        self.assertEqual(attachment.duration_ms, 3000)
        self.assertEqual(attachment.waveform, [1, 2, 3])

    def test_client_without_tariff_cannot_upload(self):
        response = self.request_upload(self.client_user)
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["code"], "TARIFF_REQUIRED")

    def test_too_large_rejected(self):
        limit = 20 * MB
        response = self.request_upload(self.specialist, size=limit + 1)
        self.assertEqual(response.status_code, 413)
        self.assertEqual(response.json()["code"], "ATTACHMENT_TOO_LARGE")
        self.assertFalse(Attachment.objects.exists())

        self.assertEqual(self.request_upload(self.specialist, size=limit).status_code, 201)
        # лимит зависит от типа
        video = self.request_upload(
            self.specialist, kind="video", mimeType="video/mp4", fileName="a.mp4", size=limit + 1
        )
        self.assertEqual(video.status_code, 201)

    def test_invalid_payload_rejected(self):
        self.assertEqual(self.request_upload(self.specialist, kind="gif").status_code, 400)
        self.assertEqual(self.request_upload(self.specialist, size=0).status_code, 400)
        self.assertEqual(self.request_upload(self.specialist, fileName="").status_code, 400)
        self.assertEqual(self.request_upload(self.specialist, mimeType="").status_code, 400)

    def test_non_member_gets_404(self):
        stranger = User.objects.create_user(username="stranger", password="p", role=ROLE_CLIENT)
        self.assertEqual(self.request_upload(stranger).status_code, 404)


class SendWithAttachmentTests(AttachmentTestCase):
    def test_send_with_attachment_marks_ready_and_serializes_url(self):
        attachment = self.make_attachment(width=640, height=480)

        response = self.send(self.specialist, text="смотри", attachmentIds=[str(attachment.pk)])

        self.assertEqual(response.status_code, 201, response.content)
        body = response.json()
        self.assertEqual(
            body["attachments"],
            [
                {
                    "id": str(attachment.pk),
                    "kind": "image",
                    "fileName": "photo.png",
                    "mimeType": "image/png",
                    "size": 1024,
                    "width": 640,
                    "height": 480,
                    "durationMs": None,
                    "waveform": None,
                    "url": f"https://files.example.com/get/{attachment.object_key}",
                }
            ],
        )
        attachment.refresh_from_db()
        self.assertEqual(attachment.status, Attachment.Status.READY)
        self.assertEqual(attachment.message_id, body["id"])
        self.storage_presigned_get.assert_called_with(attachment.object_key, 3600, "photo.png")

        published = [c.args for c in self.broadcast_mock.call_args_list if c.args[1]["type"] == "message.new"]
        self.assertEqual(len(published), 1)
        self.assertEqual(published[0][1]["data"]["attachments"][0]["id"], str(attachment.pk))

    def test_message_with_only_attachment_not_empty(self):
        attachment = self.make_attachment()
        response = self.send(self.specialist, attachmentIds=[str(attachment.pk)])
        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(response.json()["text"], "")
        self.assertEqual(len(response.json()["attachments"]), 1)

    def test_attachments_keep_attachment_ids_order(self):
        # резерв A, потом B (например, параллельные загрузки), отправка в порядке [B, A]
        first = self.request_upload(self.specialist, fileName="a.png").json()["id"]
        second = self.request_upload(
            self.specialist, kind="video", mimeType="video/mp4", fileName="b.mp4"
        ).json()["id"]

        response = self.send(self.specialist, attachmentIds=[second, first])

        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual([a["id"] for a in response.json()["attachments"]], [second, first])
        self.assertEqual(
            dict(Attachment.objects.filter(pk__in=[first, second]).values_list("id", "position")),
            {uuid.UUID(second): 0, uuid.UUID(first): 1},
        )
        history = self.client.get(self.messages_url()).json()["results"][0]
        self.assertEqual([a["id"] for a in history["attachments"]], [second, first])

        from messenger.services.push import message_preview

        message = Message.objects.get(pk=response.json()["id"])
        self.assertEqual(message_preview(message), "Видео")  # первое по порядку отправки — видео B

    def test_missing_object_rejected(self):
        self.storage_head.return_value = None
        attachment = self.make_attachment()

        response = self.send(self.specialist, text="x", attachmentIds=[str(attachment.pk)])

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["code"], "ATTACHMENT_INVALID")
        self.assertFalse(Message.objects.exists())
        attachment.refresh_from_db()
        self.assertEqual(attachment.status, Attachment.Status.PENDING)

    def test_uploaded_object_over_limit_rejected(self):
        self.storage_head.return_value = {"ContentLength": 20 * MB + 1}
        attachment = self.make_attachment()
        response = self.send(self.specialist, attachmentIds=[str(attachment.pk)])
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["code"], "ATTACHMENT_INVALID")
        self.assertFalse(Message.objects.exists())

    def test_cannot_attach_foreign_attachment(self):
        # чужой uploader
        foreign_uploader = self.make_attachment(uploader=self.client_user)
        response = self.send(self.specialist, attachmentIds=[str(foreign_uploader.pk)])
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["code"], "ATTACHMENT_INVALID")

        # другой чат
        other_specialist = User.objects.create_user(username="sp2", password="p", role=ROLE_SPECIALIST)
        other_chat = create_or_get_chat(self.client_user, other_specialist)
        other_chat_attachment = self.make_attachment(chat=other_chat)
        response = self.send(self.specialist, attachmentIds=[str(other_chat_attachment.pk)])
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["code"], "ATTACHMENT_INVALID")

        # несуществующий
        response = self.send(self.specialist, attachmentIds=[str(uuid.uuid4())])
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["code"], "ATTACHMENT_INVALID")

        self.assertFalse(Message.objects.exists())

    def test_cannot_attach_already_used_attachment(self):
        attachment = self.make_attachment()
        first = self.send(self.specialist, attachmentIds=[str(attachment.pk)])
        self.assertEqual(first.status_code, 201)
        second = self.send(self.specialist, attachmentIds=[str(attachment.pk)])
        self.assertEqual(second.status_code, 400)
        self.assertEqual(second.json()["code"], "ATTACHMENT_INVALID")

    def test_duplicate_ids_rejected(self):
        attachment = self.make_attachment()
        response = self.send(self.specialist, attachmentIds=[str(attachment.pk), str(attachment.pk)])
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["code"], "ATTACHMENT_INVALID")

    def test_voice_attachment_requires_voice_permission(self):
        self.activate_tariff()
        self.enable_voice(False)
        voice = self.make_attachment(
            uploader=self.client_user, kind=Attachment.Kind.VOICE, mime_type="audio/aac", file_name="v.aac"
        )

        response = self.send(self.client_user, attachmentIds=[str(voice.pk)])
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["code"], "VOICE_NOT_ALLOWED")
        self.assertFalse(Message.objects.exists())

        self.enable_voice(True)
        response = self.send(self.client_user, attachmentIds=[str(voice.pk)])
        self.assertEqual(response.status_code, 201, response.content)

    def test_deleted_message_hides_attachments(self):
        attachment = self.make_attachment()
        message_id = self.send(self.specialist, text="x", attachmentIds=[str(attachment.pk)]).json()["id"]
        self.auth(self.specialist)
        response = self.client.delete(f"{self.messages_url()}{message_id}/")
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["attachments"], [])

    def test_history_and_chat_list_include_attachments_without_n_plus_one(self):
        def send_with_attachment():
            attachment = self.make_attachment()
            self.send(self.specialist, attachmentIds=[str(attachment.pk)])

        def history():
            self.auth(self.specialist)
            with CaptureQueriesContext(connection) as ctx:
                response = self.client.get(self.messages_url())
            self.assertEqual(response.status_code, 200, response.content)
            return len(app_queries(ctx)), response.json()

        send_with_attachment()
        one_count, body = history()
        self.assertEqual(len(body["results"][0]["attachments"]), 1)

        send_with_attachment()
        send_with_attachment()
        three_count, body = history()
        self.assertEqual(len(body["results"]), 3)
        self.assertTrue(all(len(m["attachments"]) == 1 for m in body["results"]))
        self.assertEqual(one_count, three_count)

        response = self.client.get("/api/chats/")
        self.assertEqual(response.status_code, 200, response.content)
        payload = response.json()
        items = payload["results"] if isinstance(payload, dict) else payload
        last = items[0]["lastMessage"]
        self.assertEqual(len(last["attachments"]), 1)
        self.assertTrue(last["attachments"][0]["url"].startswith("https://files.example.com/get/"))

    def test_chat_list_attachment_queries_do_not_grow_with_chats(self):
        def make_chat_with_attachment(index):
            specialist = User.objects.create_user(username=f"sp_att_{index}", password="p", role=ROLE_SPECIALIST)
            chat = create_or_get_chat(self.client_user, specialist)
            attachment = self.make_attachment(uploader=specialist, chat=chat)
            self.auth(specialist)
            with self.captureOnCommitCallbacks(execute=True):
                response = self.client.post(
                    self.messages_url(chat), {"attachmentIds": [str(attachment.pk)]}, format="json"
                )
            self.assertEqual(response.status_code, 201, response.content)

        def list_queries():
            self.auth(self.client_user)
            with CaptureQueriesContext(connection) as ctx:
                response = self.client.get("/api/chats/")
            self.assertEqual(response.status_code, 200)
            return len(app_queries(ctx))

        make_chat_with_attachment(1)
        base = list_queries()
        make_chat_with_attachment(2)
        make_chat_with_attachment(3)
        self.assertEqual(list_queries(), base)


class CleanupTests(AttachmentTestCase):
    def test_cleanup_removes_stale_pending(self):
        stale = self.make_attachment()
        fresh = self.make_attachment()
        message = Message.objects.create(chat=self.chat, sender=self.specialist, text="x")
        linked_old = self.make_attachment(message=message, status=Attachment.Status.READY)
        old = timezone.now() - timedelta(hours=25)
        Attachment.objects.filter(pk__in=[stale.pk, linked_old.pk]).update(created_at=old)

        removed = tasks.cleanup_pending_attachments()

        self.assertEqual(removed, 1)
        self.assertFalse(Attachment.objects.filter(pk=stale.pk).exists())
        self.assertTrue(Attachment.objects.filter(pk=fresh.pk).exists())
        self.assertTrue(Attachment.objects.filter(pk=linked_old.pk).exists())
        self.storage_delete.assert_called_once_with(stale.object_key)

    def test_cleanup_keeps_row_when_storage_delete_fails(self):
        stale = self.make_attachment()
        Attachment.objects.filter(pk=stale.pk).update(created_at=timezone.now() - timedelta(hours=25))
        self.storage_delete.side_effect = RuntimeError("minio down")

        removed = tasks.cleanup_pending_attachments()

        self.assertEqual(removed, 0)
        self.assertTrue(Attachment.objects.filter(pk=stale.pk).exists())

    def test_beat_schedule_runs_cleanup_hourly(self):
        from config.celery import app as celery_app

        entry = celery_app.conf.beat_schedule["cleanup-pending-attachments"]
        self.assertEqual(entry["task"], "messenger.tasks.cleanup_pending_attachments")
        self.assertEqual(entry["schedule"].minute, {0})
