import base64
import hashlib
import json
import threading
import time
from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock, patch

from aioapns.common import NotificationResult
from django.contrib.auth import get_user_model
from django.db import connection
from django.test import SimpleTestCase, TransactionTestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from livekit.api import AccessToken, TokenVerifier
from push_notifications.models import GCMDevice

from account.models import ROLE_CLIENT, ROLE_SPECIALIST, Notification
from chat_access.models import AccessOrder, BlockedChat
from chat_access.services.chat_commands import create_or_get_chat
from common.notifications import send_data_push
from messenger import tasks
from messenger.clients import apns, livekit
from messenger.models import Call, ChatMember, Message, VoipDevice
from messenger.tests.base import MessengerTestCase, activate_tariff
from messenger.tests.test_attachments import app_queries

User = get_user_model()

LK_KEY = "lk_test_key"
LK_SECRET = "lk_test_secret_lk_test_secret_0123456789"
LIVEKIT_SETTINGS = {
    "LIVEKIT_URL": "wss://rtc.example.com",
    "LIVEKIT_API_URL": "http://livekit:7880",
    "LIVEKIT_API_KEY": LK_KEY,
    "LIVEKIT_API_SECRET": LK_SECRET,
}
WEBHOOK_URL = "/api/messenger/livekit-webhook/"


@override_settings(**LIVEKIT_SETTINGS)
class LiveKitClientTests(SimpleTestCase):
    def test_access_token_grants_room_and_identity(self):
        user = User(id=42, first_name="Иван", last_name="Петров", username="ivan")
        token = livekit.access_token(user, "call_abc", video=False)

        claims = TokenVerifier(LK_KEY, LK_SECRET).verify(token)
        self.assertEqual(claims.identity, "42")
        self.assertEqual(claims.name, "Иван Петров")
        self.assertTrue(claims.video.room_join)
        self.assertEqual(claims.video.room, "call_abc")
        self.assertEqual(claims.video.can_publish_sources, ["microphone"])

        video_token = livekit.access_token(user, "call_abc", video=True)
        video_claims = TokenVerifier(LK_KEY, LK_SECRET).verify(video_token)
        self.assertEqual(sorted(video_claims.video.can_publish_sources), ["camera", "microphone"])


@override_settings(APNS_KEY_PATH="/keys/apns.p8", APNS_KEY_ID="KEYID", APNS_TEAM_ID="TEAM", APNS_BUNDLE_ID="kg.profichat")
class ApnsClientTests(MessengerTestCase):
    def _send(self, status):
        client = MagicMock()
        client.send_notification = AsyncMock(return_value=NotificationResult("id", status, "Unregistered"))
        with patch("messenger.clients.apns.APNs", return_value=client) as apns_cls:
            ok = apns.send_voip("tok-1", {"type": "incoming_call"})
        return ok, apns_cls, client

    def test_send_voip_uses_voip_topic_and_push_type(self):
        VoipDevice.objects.create(user=self.specialist, token="tok-1", bundle_id="kg.profichat")
        ok, apns_cls, client = self._send("200")

        self.assertTrue(ok)
        self.assertEqual(apns_cls.call_args.kwargs["topic"], "kg.profichat.voip")
        request = client.send_notification.await_args.args[0]
        self.assertEqual(request.push_type.value, "voip")
        self.assertEqual(request.apns_topic, "kg.profichat.voip")
        self.assertEqual(request.device_token, "tok-1")
        self.assertEqual(request.message["type"], "incoming_call")
        self.assertTrue(VoipDevice.objects.get(token="tok-1").active)

    def test_send_voip_410_deactivates_device(self):
        VoipDevice.objects.create(user=self.specialist, token="tok-1", bundle_id="kg.profichat")
        ok, _, _ = self._send("410")

        self.assertFalse(ok)
        self.assertFalse(VoipDevice.objects.get(token="tok-1").active)


class DataPushTests(MessengerTestCase):
    def test_send_data_push_is_data_only_high_priority_with_ttl(self):
        GCMDevice.objects.create(user=self.specialist, registration_id="fcm-1", active=True, cloud_message_type="FCM")
        with patch.object(GCMDevice, "send_message", return_value=MagicMock(success_count=1)) as send_message:
            ok = send_data_push(self.specialist, {"type": "incoming_call", "callId": "abc", "n": 1}, ttl_seconds=45)

        self.assertTrue(ok)
        message = send_message.call_args.args[0]
        self.assertIsNone(message.notification)
        self.assertEqual(message.data, {"type": "incoming_call", "callId": "abc", "n": "1"})
        self.assertEqual(message.android.priority, "high")
        self.assertEqual(message.android.ttl, timedelta(seconds=45))
        self.assertIsNone(message.android.notification)

    def test_send_data_push_omits_none_values(self):
        # None не превращается в строку "None": ключ просто не отправляется
        GCMDevice.objects.create(user=self.specialist, registration_id="fcm-1", active=True, cloud_message_type="FCM")
        with patch.object(GCMDevice, "send_message", return_value=MagicMock(success_count=1)) as send_message:
            send_data_push(self.specialist, {"type": "incoming_call", "callerPhoto": None}, ttl_seconds=45)
        self.assertEqual(send_message.call_args.args[0].data, {"type": "incoming_call"})


@override_settings(**LIVEKIT_SETTINGS)
class CallTestCase(MessengerTestCase):
    def setUp(self):
        super().setUp()
        self.livekit_mocks = {}
        for name, kwargs in (
            ("create_room", {}),
            ("delete_room", {}),
            ("access_token", {"return_value": "lk-token"}),
        ):
            patcher = patch(f"messenger.clients.livekit.{name}", **kwargs)
            self.livekit_mocks[name] = patcher.start()
            self.addCleanup(patcher.stop)

        expire_patcher = patch("messenger.tasks.expire_call.apply_async")
        self.expire_mock = expire_patcher.start()
        self.addCleanup(expire_patcher.stop)

        call_push_patcher = patch("messenger.tasks.send_call_push.delay")
        self.call_push_mock = call_push_patcher.start()
        self.addCleanup(call_push_patcher.stop)

        message_push_patcher = patch("messenger.services.push.send_push")
        self.message_push_mock = message_push_patcher.start()
        self.addCleanup(message_push_patcher.stop)

    # --- helpers ---

    def start(self, user, kind="audio", chat=None):
        self.auth(user)
        with self.captureOnCommitCallbacks(execute=True):
            return self.client.post(
                f"/api/chats/{(chat or self.chat).channel_id}/calls/", {"kind": kind}, format="json"
            )

    def act(self, user, call, action):
        self.auth(user)
        with self.captureOnCommitCallbacks(execute=True):
            return self.client.post(f"/api/calls/{call.pk}/{action}/", format="json")

    def ring(self, kind="audio", caller=None):
        response = self.start(caller or self.client_user, kind=kind)
        self.assertEqual(response.status_code, 201, response.content)
        return Call.objects.get(pk=response.json()["call"]["id"])

    def events(self):
        return [(call.args[0], call.args[1]["type"], call.args[1]["data"]) for call in self.broadcast_mock.call_args_list]

    def event_types(self, user):
        channel = f"personal:{user.pk}"
        return [event_type for channels, event_type, _ in self.events() if channel in channels]

    def assertError(self, response, status_code, code):
        self.assertEqual(response.status_code, status_code, response.content)
        self.assertEqual(response.json()["code"], code, response.content)

    def signed_webhook(self, payload, secret=LK_SECRET):
        body = json.dumps(payload)
        digest = base64.b64encode(hashlib.sha256(body.encode()).digest()).decode()
        token = AccessToken(LK_KEY, secret).with_sha256(digest).to_jwt()
        with self.captureOnCommitCallbacks(execute=True):
            return self.client.generic(
                "POST", WEBHOOK_URL, body, content_type="application/webhook+json", HTTP_AUTHORIZATION=token
            )


class StartCallTests(CallTestCase):
    def test_start_call_rings_and_schedules_timeout(self):
        self.activate_tariff()
        response = self.start(self.client_user, kind="video")

        self.assertEqual(response.status_code, 201, response.content)
        body = response.json()
        call = Call.objects.get(pk=body["call"]["id"])
        self.assertEqual(call.status, Call.Status.RINGING)
        self.assertEqual(call.kind, Call.Kind.VIDEO)
        self.assertEqual(call.caller, self.client_user)
        self.assertEqual(call.callee, self.specialist)
        self.assertEqual(call.room_name, f"call_{call.pk}")
        self.assertEqual(body["livekitUrl"], "wss://rtc.example.com")
        self.assertEqual(body["token"], "lk-token")
        self.assertEqual(body["call"]["status"], "ringing")
        self.assertEqual(body["call"]["channelId"], self.chat.channel_id)
        self.assertEqual(body["call"]["callerId"], self.client_user.pk)
        self.assertEqual(body["call"]["calleeId"], self.specialist.pk)

        self.livekit_mocks["create_room"].assert_called_once_with(call.room_name)
        self.livekit_mocks["access_token"].assert_called_once_with(self.client_user, call.room_name, video=True)
        self.call_push_mock.assert_called_once_with(str(call.pk))
        self.expire_mock.assert_called_once_with((str(call.pk),), countdown=45)

        message = Message.objects.get(call=call)
        self.assertEqual(message.type, Message.Type.CALL)
        self.assertEqual(message.sender, self.client_user)
        self.chat.refresh_from_db()
        self.assertEqual(self.chat.last_message_id, message.pk)
        # звонковое сообщение не увеличивает непрочитанные и не шлёт обычный пуш
        self.assertEqual(ChatMember.objects.get(chat=self.chat, user=self.specialist).unread_count, 0)
        self.message_push_mock.assert_not_called()

        self.assertIn("call.incoming", self.event_types(self.specialist))
        self.assertNotIn("call.incoming", self.event_types(self.client_user))
        self.assertIn("message.new", self.event_types(self.specialist))
        self.assertIn("message.new", self.event_types(self.client_user))
        incoming = next(data for _, t, data in self.events() if t == "call.incoming")
        self.assertEqual(incoming["call"]["id"], str(call.pk))
        self.assertEqual(incoming["caller"]["id"], self.client_user.pk)
        self.assertIsNone(incoming["caller"]["photo"])

    @override_settings(DOMAIN="api.example.com")
    def test_call_incoming_and_push_carry_caller_photo(self):
        # update() без save(): User.save синхронизирует профиль в GetStream
        User.objects.filter(pk=self.client_user.pk).update(photo="user/photos/2026/10/27/me.jpg")
        self.client_user.refresh_from_db()
        self.activate_tariff()
        call = self.ring()
        photo_url = "https://api.example.com/media/user/photos/2026/10/27/me.jpg"

        incoming = next(data for _, t, data in self.events() if t == "call.incoming")
        self.assertEqual(incoming["caller"]["photo"], photo_url)

        VoipDevice.objects.create(user=self.specialist, token="voip-1", bundle_id="kg.profichat")
        with patch("messenger.clients.apns.send_voip", return_value=True) as send_voip, \
                patch("messenger.services.push.send_data_push", return_value=True) as send_data:
            tasks.send_call_push(str(call.pk))
        self.assertEqual(send_voip.call_args.args[1]["callerPhoto"], photo_url)
        self.assertEqual(send_data.call_args.args[1]["callerPhoto"], photo_url)

    def test_client_without_tariff_cannot_call_or_accept(self):
        self.assertError(self.start(self.client_user), 403, "TARIFF_REQUIRED")
        self.assertError(self.start(self.specialist), 403, "TARIFF_REQUIRED")
        self.assertFalse(Call.objects.exists())

        order = self.activate_tariff()
        call = self.ring(caller=self.specialist)
        AccessOrder.objects.filter(pk=order.pk).update(expires_at=timezone.now() - timedelta(minutes=1))

        self.assertError(self.act(self.client_user, call, "accept"), 403, "TARIFF_REQUIRED")
        call.refresh_from_db()
        self.assertEqual(call.status, Call.Status.RINGING)

    def test_blacklisted_companion_call_not_allowed(self):
        self.activate_tariff()
        BlockedChat.objects.create(user=self.specialist, chat=self.chat)

        self.assertError(self.start(self.client_user), 403, "CALL_NOT_ALLOWED")
        self.assertFalse(Call.objects.exists())
        self.livekit_mocks["create_room"].assert_not_called()

    def test_callee_disabled_call_kind_not_allowed(self):
        self.activate_tariff()
        for kind, flag in (("audio", "can_audio_call"), ("video", "can_video_call")):
            with self.subTest(kind=kind):
                User.objects.filter(pk=self.specialist.pk).update(can_audio_call=True, can_video_call=True)
                User.objects.filter(pk=self.specialist.pk).update(**{flag: False})

                self.assertError(self.start(self.client_user, kind=kind), 403, "CALL_NOT_ALLOWED")
                self.assertFalse(Call.objects.exists())
                self.assertFalse(Message.objects.filter(type=Message.Type.CALL).exists())
                self.livekit_mocks["create_room"].assert_not_called()

        # другой тип звонка при этом разрешён
        response = self.start(self.client_user, kind="audio")
        self.assertEqual(response.status_code, 201, response.content)

    def test_callee_disabled_calls_checked_before_busy(self):
        # даже когда собеседник занят, запрет звонков — 403 без BUSY-записи и сообщения
        self.activate_tariff()
        other_client = User.objects.create_user(username="client_2", password="pass", role=ROLE_CLIENT)
        other_chat = create_or_get_chat(other_client, self.specialist)
        self.activate_tariff(chat=other_chat)
        self.ring()
        User.objects.filter(pk=self.specialist.pk).update(can_audio_call=False)

        self.assertError(self.start(other_client, chat=other_chat), 403, "CALL_NOT_ALLOWED")
        self.assertEqual(Call.objects.count(), 1)
        self.assertFalse(Message.objects.filter(chat=other_chat, type=Message.Type.CALL).exists())

    def test_second_call_while_active_is_busy(self):
        self.activate_tariff()
        first = self.ring()

        other_client = User.objects.create_user(username="client_2", password="pass", role=ROLE_CLIENT)
        other_chat = create_or_get_chat(other_client, self.specialist)
        self.activate_tariff(chat=other_chat)
        self.broadcast_mock.reset_mock()
        self.expire_mock.reset_mock()
        self.call_push_mock.reset_mock()
        self.livekit_mocks["create_room"].reset_mock()

        response = self.start(other_client, chat=other_chat)

        self.assertEqual(response.status_code, 201, response.content)
        body = response.json()
        self.assertEqual(body["call"]["status"], "busy")
        self.assertIsNone(body["token"])
        busy = Call.objects.get(pk=body["call"]["id"])
        self.assertEqual(busy.status, Call.Status.BUSY)
        self.assertIsNotNone(busy.ended_at)
        self.assertTrue(Message.objects.filter(call=busy, chat=other_chat, type=Message.Type.CALL).exists())
        self.livekit_mocks["create_room"].assert_not_called()
        self.expire_mock.assert_not_called()
        self.call_push_mock.assert_not_called()
        self.assertNotIn("call.incoming", self.event_types(self.specialist))
        self.assertIn("message.new", self.event_types(other_client))

        # звонящий тоже «занят», пока у него идёт звонок
        third = User.objects.create_user(username="specialist_2", password="pass", role=ROLE_SPECIALIST)
        third_chat = create_or_get_chat(self.client_user, third)
        self.activate_tariff(chat=third_chat)
        response = self.start(self.client_user, chat=third_chat)
        self.assertEqual(response.json()["call"]["status"], "busy")

        first.refresh_from_db()
        self.assertEqual(first.status, Call.Status.RINGING)

    def test_stale_ringing_call_does_not_block(self):
        self.activate_tariff()
        stale = self.ring()
        Call.objects.filter(pk=stale.pk).update(created_at=timezone.now() - timedelta(minutes=5))

        response = self.start(self.client_user)
        self.assertEqual(response.json()["call"]["status"], "ringing")


class CallTransitionTests(CallTestCase):
    def setUp(self):
        super().setUp()
        self.activate_tariff()

    def test_accept_returns_token_and_publishes(self):
        call = self.ring()
        self.broadcast_mock.reset_mock()

        response = self.act(self.specialist, call, "accept")

        self.assertEqual(response.status_code, 200, response.content)
        body = response.json()
        self.assertEqual(body["call"]["status"], "accepted")
        self.assertIsNotNone(body["call"]["answeredAt"])
        self.assertEqual(body["livekitUrl"], "wss://rtc.example.com")
        self.assertEqual(body["token"], "lk-token")
        self.livekit_mocks["access_token"].assert_called_with(self.specialist, call.room_name, video=False)
        call.refresh_from_db()
        self.assertEqual(call.status, Call.Status.ACCEPTED)
        for user in (self.client_user, self.specialist):
            self.assertIn("call.accepted", self.event_types(user))
            self.assertIn("message.updated", self.event_types(user))

    def test_non_participant_cannot_accept_call(self):
        call = self.ring()
        stranger = User.objects.create_user(username="stranger", password="pass", role=ROLE_SPECIALIST)

        self.assertError(self.act(stranger, call, "accept"), 404, "CALL_NOT_FOUND")
        self.auth(stranger)
        self.assertError(self.client.get(f"/api/calls/{call.pk}/"), 404, "CALL_NOT_FOUND")
        # звонящий не может принять свой же звонок
        self.assertError(self.act(self.client_user, call, "accept"), 403, "CALL_NOT_ALLOWED")
        call.refresh_from_db()
        self.assertEqual(call.status, Call.Status.RINGING)

    def test_decline_cancel_end_transitions_and_duration(self):
        declined = self.ring()
        response = self.act(self.specialist, declined, "decline")
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["status"], "declined")
        declined.refresh_from_db()
        self.assertEqual(declined.status, Call.Status.DECLINED)
        self.assertIsNotNone(declined.ended_at)
        self.livekit_mocks["delete_room"].assert_called_with(declined.room_name)
        self.assertIn("call.declined", self.event_types(self.client_user))
        updated = [data for _, t, data in self.events() if t == "message.updated"][-1]
        self.assertEqual(updated["call"]["status"], "declined")

        cancelled = self.ring()
        response = self.act(self.client_user, cancelled, "cancel")
        self.assertEqual(response.json()["status"], "cancelled")
        self.assertIn("call.cancelled", self.event_types(self.specialist))

        # end/ от звонящего до ответа = отмена
        ringing = self.ring()
        response = self.act(self.client_user, ringing, "end")
        self.assertEqual(response.json()["status"], "cancelled")

        talk = self.ring()
        self.act(self.specialist, talk, "accept")
        Call.objects.filter(pk=talk.pk).update(answered_at=timezone.now() - timedelta(seconds=90))
        # истёкший во время разговора тариф не мешает завершить звонок
        AccessOrder.objects.filter(chat=self.chat).update(expires_at=timezone.now() - timedelta(minutes=1))
        response = self.act(self.specialist, talk, "end")
        self.assertEqual(response.status_code, 200, response.content)
        talk.refresh_from_db()
        self.assertEqual(talk.status, Call.Status.ENDED)
        self.assertEqual(talk.end_reason, "hangup")
        self.assertIn(talk.duration_seconds, (90, 91))
        self.assertEqual(response.json()["durationSeconds"], talk.duration_seconds)
        self.assertIn("call.ended", self.event_types(self.client_user))
        self.livekit_mocks["delete_room"].assert_called_with(talk.room_name)

        self.auth(self.client_user)
        detail = self.client.get(f"/api/calls/{talk.pk}/")
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(detail.json()["status"], "ended")

    def test_invalid_transition_409(self):
        call = self.ring()
        self.act(self.specialist, call, "decline")

        self.assertError(self.act(self.specialist, call, "accept"), 409, "CALL_INVALID_STATE")
        self.assertError(self.act(self.client_user, call, "cancel"), 409, "CALL_INVALID_STATE")
        self.assertError(self.act(self.client_user, call, "end"), 409, "CALL_INVALID_STATE")

        accepted = self.ring()
        self.act(self.specialist, accepted, "accept")
        self.assertError(self.act(self.client_user, accepted, "cancel"), 409, "CALL_INVALID_STATE")
        self.assertError(self.act(self.specialist, accepted, "decline"), 409, "CALL_INVALID_STATE")

    def test_expire_marks_missed_and_notifies(self):
        call = self.ring()
        self.broadcast_mock.reset_mock()

        with patch("common.notifications.send_push", return_value={"ok": True}) as send_push, \
                self.captureOnCommitCallbacks(execute=True):
            tasks.expire_call(str(call.pk))

        call.refresh_from_db()
        self.assertEqual(call.status, Call.Status.MISSED)
        self.assertEqual(call.end_reason, "timeout")
        self.assertIsNotNone(call.ended_at)
        self.assertIn("call.missed", self.event_types(self.specialist))
        self.assertIn("call.missed", self.event_types(self.client_user))
        self.livekit_mocks["delete_room"].assert_called_with(call.room_name)
        notification = Notification.objects.get(recipient=self.specialist)
        self.assertEqual(notification.notification_type, "missed_call")
        self.assertEqual(notification.title, "Пропущенный звонок")
        self.assertEqual(notification.payload["callId"], str(call.pk))
        self.assertEqual(notification.payload["channelId"], self.chat.channel_id)
        send_push.assert_called_once()

        # принятый звонок таймаут не трогает
        accepted = self.ring()
        self.act(self.specialist, accepted, "accept")
        with patch("common.notifications.send_push", return_value={"ok": True}) as send_push, \
                self.captureOnCommitCallbacks(execute=True):
            tasks.expire_call(str(accepted.pk))
        accepted.refresh_from_db()
        self.assertEqual(accepted.status, Call.Status.ACCEPTED)
        send_push.assert_not_called()


class LiveKitWebhookTests(CallTestCase):
    def setUp(self):
        super().setUp()
        self.activate_tariff()
        participants_patcher = patch("messenger.clients.livekit.room_participants", return_value=set())
        self.room_participants = participants_patcher.start()
        self.addCleanup(participants_patcher.stop)
        recheck_patcher = patch("messenger.tasks.check_call_room.apply_async")
        self.recheck_mock = recheck_patcher.start()
        self.addCleanup(recheck_patcher.stop)

    def accepted_call(self):
        call = self.ring()
        self.act(self.specialist, call, "accept")
        self.client.force_authenticate(user=None)
        self.broadcast_mock.reset_mock()
        return call

    def participant_left(self, call, user):
        return self.signed_webhook({
            "event": "participant_left",
            "room": {"name": call.room_name},
            "participant": {"identity": str(user.pk)},
        })

    def test_webhook_rejects_bad_signature(self):
        payload = {"event": "room_finished", "room": {"name": "call_x"}}
        response = self.signed_webhook(payload, secret="wrong_secret_wrong_secret_wrong_secret")
        self.assertEqual(response.status_code, 401, response.content)

        response = self.client.generic(
            "POST", WEBHOOK_URL, json.dumps(payload), content_type="application/webhook+json"
        )
        self.assertEqual(response.status_code, 401, response.content)

        # подпись от другого тела
        body = json.dumps(payload)
        digest = base64.b64encode(hashlib.sha256(b"other").digest()).decode()
        token = AccessToken(LK_KEY, LK_SECRET).with_sha256(digest).to_jwt()
        response = self.client.generic(
            "POST", WEBHOOK_URL, body, content_type="application/webhook+json", HTTP_AUTHORIZATION=token
        )
        self.assertEqual(response.status_code, 401, response.content)

    def test_webhook_participant_left_ends_call(self):
        call = self.ring()
        self.act(self.specialist, call, "accept")
        Call.objects.filter(pk=call.pk).update(answered_at=timezone.now() - timedelta(seconds=30))
        self.client.force_authenticate(user=None)
        self.broadcast_mock.reset_mock()

        response = self.signed_webhook({
            "event": "participant_left",
            "room": {"name": call.room_name},
            "participant": {"identity": str(self.client_user.pk)},
        })

        self.assertEqual(response.status_code, 200, response.content)
        call.refresh_from_db()
        self.assertEqual(call.status, Call.Status.ENDED)
        self.assertEqual(call.end_reason, "disconnected")
        self.assertIn(call.duration_seconds, (30, 31))
        self.assertIn("call.ended", self.event_types(self.specialist))

        # повтор и неизвестные комнаты/события — 200 без изменений
        for payload in (
            {"event": "room_finished", "room": {"name": call.room_name}},
            {"event": "room_finished", "room": {"name": "call_00000000-0000-0000-0000-000000000000"}},
            {"event": "room_finished", "room": {"name": "some-other-room"}},
            {"event": "track_published", "room": {"name": call.room_name}},
        ):
            self.assertEqual(self.signed_webhook(payload).status_code, 200)
        call.refresh_from_db()
        self.assertEqual(call.end_reason, "disconnected")

    def test_participant_left_keeps_call_while_someone_remains(self):
        call = self.accepted_call()
        # LiveKit может ещё перечислять ушедшего — он не считается оставшимся
        self.room_participants.return_value = {str(self.specialist.pk), str(self.client_user.pk)}

        response = self.participant_left(call, self.client_user)

        self.assertEqual(response.status_code, 200, response.content)
        self.room_participants.assert_called_once_with(call.room_name)
        call.refresh_from_db()
        self.assertEqual(call.status, Call.Status.ACCEPTED)
        self.assertNotIn("call.ended", self.event_types(self.specialist))
        self.recheck_mock.assert_not_called()

    def test_participant_left_only_leaver_listed_ends_call(self):
        call = self.accepted_call()
        self.room_participants.return_value = {str(self.client_user.pk)}

        self.participant_left(call, self.client_user)

        call.refresh_from_db()
        self.assertEqual(call.status, Call.Status.ENDED)

    def test_participant_left_livekit_unreachable_schedules_recheck(self):
        call = self.accepted_call()
        self.room_participants.side_effect = livekit.LiveKitError("down")

        response = self.participant_left(call, self.client_user)

        self.assertEqual(response.status_code, 200, response.content)
        call.refresh_from_db()
        self.assertEqual(call.status, Call.Status.ACCEPTED)
        self.recheck_mock.assert_called_once_with((str(call.pk),), countdown=30)

    def test_recheck_task_ends_call_when_room_empty(self):
        call = self.accepted_call()

        with self.captureOnCommitCallbacks(execute=True):
            tasks.check_call_room(str(call.pk))

        call.refresh_from_db()
        self.assertEqual(call.status, Call.Status.ENDED)
        self.assertEqual(call.end_reason, "disconnected")

    def test_recheck_task_keeps_call_when_occupied_or_unreachable(self):
        call = self.accepted_call()
        for side_effect, value in ((None, {str(self.specialist.pk)}), (livekit.LiveKitError("down"), set())):
            self.room_participants.side_effect = side_effect
            self.room_participants.return_value = value
            with self.captureOnCommitCallbacks(execute=True):
                tasks.check_call_room(str(call.pk))
            call.refresh_from_db()
            self.assertEqual(call.status, Call.Status.ACCEPTED)
        # повторно не планируется: дальше страхуют room_finished и reconcile_calls
        self.recheck_mock.assert_not_called()

    def test_webhook_room_finished_ends_call(self):
        call = self.ring()
        self.act(self.specialist, call, "accept")
        self.client.force_authenticate(user=None)

        response = self.signed_webhook({"event": "room_finished", "room": {"name": call.room_name}})

        self.assertEqual(response.status_code, 200, response.content)
        call.refresh_from_db()
        self.assertEqual(call.status, Call.Status.ENDED)


class VoipDeviceTests(CallTestCase):
    def test_voip_device_register_and_push(self):
        self.auth(self.specialist)
        response = self.client.post(
            "/api/messenger/voip-devices/", {"token": "voip-1", "bundleId": "kg.profichat"}, format="json"
        )
        self.assertEqual(response.status_code, 201, response.content)
        device = VoipDevice.objects.get(token="voip-1")
        self.assertEqual(device.user, self.specialist)
        self.assertTrue(device.active)

        # тот же токен с другого аккаунта перепривязывается
        self.auth(self.client_user)
        self.client.post("/api/messenger/voip-devices/", {"token": "voip-1", "bundleId": "kg.profichat"}, format="json")
        self.assertEqual(VoipDevice.objects.get(token="voip-1").user, self.client_user)
        self.auth(self.specialist)
        self.client.post("/api/messenger/voip-devices/", {"token": "voip-1", "bundleId": "kg.profichat"}, format="json")
        VoipDevice.objects.create(user=self.specialist, token="voip-dead", bundle_id="kg.profichat", active=False)

        self.activate_tariff()
        call = self.ring(kind="video")
        with patch("messenger.clients.apns.send_voip", return_value=True) as send_voip, \
                patch("messenger.services.push.send_data_push", return_value=True) as send_data:
            tasks.send_call_push(str(call.pk))

        send_voip.assert_called_once()
        token, payload = send_voip.call_args.args
        self.assertEqual(token, "voip-1")
        expected = {
            "type": "incoming_call",
            "callId": str(call.pk),
            "channelId": self.chat.channel_id,
            "kind": "video",
            "callerId": self.client_user.pk,
            "callerName": "client_1",
            "callerPhoto": None,
        }
        for key, value in expected.items():
            self.assertEqual(payload[key], value, key)
        send_data.assert_called_once()
        self.assertEqual(send_data.call_args.args[0], self.specialist)
        data = send_data.call_args.args[1]
        for key, value in expected.items():
            self.assertEqual(data[key], value, key)
        self.assertEqual(send_data.call_args.kwargs["ttl_seconds"], 45)

        # ответивший звонок пушить уже не нужно
        self.act(self.specialist, call, "accept")
        with patch("messenger.clients.apns.send_voip") as send_voip, \
                patch("messenger.services.push.send_data_push") as send_data:
            tasks.send_call_push(str(call.pk))
        send_voip.assert_not_called()
        send_data.assert_not_called()

        self.auth(self.specialist)
        response = self.client.delete("/api/messenger/voip-devices/voip-1/")
        self.assertEqual(response.status_code, 204, response.content)
        self.assertFalse(VoipDevice.objects.filter(token="voip-1").exists())
        # чужой токен удалить нельзя (тихо игнорируется)
        self.auth(self.client_user)
        self.client.delete("/api/messenger/voip-devices/voip-dead/")
        self.assertTrue(VoipDevice.objects.filter(token="voip-dead").exists())


class CallMessageTests(CallTestCase):
    def test_call_message_in_history(self):
        self.activate_tariff()
        call = self.ring(kind="video")
        self.act(self.specialist, call, "decline")

        self.auth(self.specialist)
        response = self.client.get(f"/api/chats/{self.chat.channel_id}/messages/")
        self.assertEqual(response.status_code, 200, response.content)
        [item] = response.json()["results"]
        self.assertEqual(item["type"], "call")
        self.assertEqual(item["senderId"], self.client_user.pk)
        self.assertEqual(
            set(item["call"]),
            {
                "id", "channelId", "callerId", "calleeId", "kind", "status", "createdAt",
                "answeredAt", "endedAt", "durationSeconds", "endReason",
            },
        )
        self.assertEqual(item["call"]["id"], str(call.pk))
        self.assertEqual(item["call"]["status"], "declined")
        self.assertEqual(item["call"]["kind"], "video")
        self.assertEqual(item["call"]["channelId"], self.chat.channel_id)

        # список чатов: lastMessage со звонком, shouldReply не включается
        [chat_item] = self.client.get("/api/chats/").json()
        self.assertEqual(chat_item["lastMessage"]["call"]["status"], "declined")
        self.assertFalse(chat_item["shouldReply"])
        self.assertEqual(chat_item["unreadCount"], 0)

        # без N+1: число запросов истории не растёт с числом звонков
        with CaptureQueriesContext(connection) as one:
            self.client.get(f"/api/chats/{self.chat.channel_id}/messages/")
        for _ in range(3):
            self.act(self.specialist, self.ring(), "decline")
        self.auth(self.specialist)
        with CaptureQueriesContext(connection) as many:
            response = self.client.get(f"/api/chats/{self.chat.channel_id}/messages/")
        self.assertEqual(len(response.json()["results"]), 4)
        self.assertEqual(len(app_queries(one)), len(app_queries(many)))

        # обычное сообщение — call: null
        self.auth(self.client_user)
        with self.captureOnCommitCallbacks(execute=True):
            msg = self.client.post(
                f"/api/chats/{self.chat.channel_id}/messages/", {"text": "hi"}, format="json"
            ).json()
        self.assertIsNone(msg["call"])

    def test_mark_read_does_not_count_call_messages(self):
        self.activate_tariff()
        regular = Message.objects.create(chat=self.chat, sender=self.specialist, text="hello")
        self.ring(caller=self.specialist)  # звонковое сообщение от собеседника после прочитанного
        self.auth(self.client_user)
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(f"/api/chats/{self.chat.channel_id}/read/", {"lastReadMessageId": regular.pk}, format="json")
        self.assertEqual(ChatMember.objects.get(chat=self.chat, user=self.client_user).unread_count, 0)


class StaleCallTests(CallTestCase):
    """Зависшие звонки: потерянный таймаут/вебхук, рестарт LiveKit."""

    def setUp(self):
        super().setUp()
        self.activate_tariff()
        rooms_patcher = patch("messenger.clients.livekit.existing_rooms")
        self.existing_rooms = rooms_patcher.start()
        self.addCleanup(rooms_patcher.stop)

    def accepted_call(self, answered_ago=timedelta(seconds=30)):
        call = self.ring()
        self.act(self.specialist, call, "accept")
        Call.objects.filter(pk=call.pk).update(answered_at=timezone.now() - answered_ago)
        call.refresh_from_db()
        return call

    def reconcile(self):
        with patch("common.notifications.send_push", return_value={"ok": True}), \
                self.captureOnCommitCallbacks(execute=True):
            return tasks.reconcile_calls()

    def test_reconcile_ends_accepted_when_room_missing(self):
        call = self.accepted_call()
        self.existing_rooms.return_value = set()
        self.broadcast_mock.reset_mock()

        stats = self.reconcile()

        self.existing_rooms.assert_called_once_with([call.room_name])
        call.refresh_from_db()
        self.assertEqual(call.status, Call.Status.ENDED)
        self.assertEqual(call.end_reason, "disconnected")
        self.assertIn(call.duration_seconds, (30, 31))
        self.assertEqual(stats["disconnected"], 1)
        self.assertIn("call.ended", self.event_types(self.client_user))
        self.assertIn("call.ended", self.event_types(self.specialist))

    def test_reconcile_keeps_accepted_when_room_present(self):
        call = self.accepted_call()
        self.existing_rooms.return_value = {call.room_name}
        self.reconcile()
        call.refresh_from_db()
        self.assertEqual(call.status, Call.Status.ACCEPTED)

        # LiveKit недоступен — проверку комнат пропускаем, звонок не трогаем
        self.existing_rooms.side_effect = livekit.LiveKitError("down")
        self.reconcile()
        call.refresh_from_db()
        self.assertEqual(call.status, Call.Status.ACCEPTED)

    def test_reconcile_hard_cap_ends_old_accepted(self):
        call = self.accepted_call(answered_ago=timedelta(seconds=7201))
        self.existing_rooms.return_value = {call.room_name}

        stats = self.reconcile()

        call.refresh_from_db()
        self.assertEqual(call.status, Call.Status.ENDED)
        self.assertEqual(call.end_reason, "max_duration")
        self.assertIn(call.duration_seconds, (7201, 7202))
        self.assertEqual(stats["max_duration"], 1)

    @override_settings(MESSENGER_CALL_MAX_DURATION_SECONDS=600)
    def test_hard_cap_uses_setting(self):
        call = self.accepted_call(answered_ago=timedelta(seconds=601))
        self.existing_rooms.return_value = {call.room_name}
        self.reconcile()
        call.refresh_from_db()
        self.assertEqual(call.end_reason, "max_duration")

    def test_reconcile_expires_stale_ringing(self):
        call = self.ring()
        Call.objects.filter(pk=call.pk).update(created_at=timezone.now() - timedelta(minutes=5))
        self.existing_rooms.return_value = set()

        stats = self.reconcile()

        call.refresh_from_db()
        self.assertEqual(call.status, Call.Status.MISSED)
        self.assertEqual(call.end_reason, "timeout")
        self.assertEqual(stats["missed"], 1)
        self.assertTrue(
            Notification.objects.filter(recipient=self.specialist, notification_type="missed_call").exists()
        )
        # свежий RINGING не трогается
        fresh = self.ring()
        self.reconcile()
        fresh.refresh_from_db()
        self.assertEqual(fresh.status, Call.Status.RINGING)

    def test_busy_ignores_over_cap_accepted(self):
        self.accepted_call(answered_ago=timedelta(hours=3))
        response = self.start(self.client_user)
        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(response.json()["call"]["status"], "ringing")

    def test_accept_stale_ringing_409_and_missed(self):
        call = self.ring()
        Call.objects.filter(pk=call.pk).update(created_at=timezone.now() - timedelta(seconds=61))
        self.broadcast_mock.reset_mock()

        with patch("common.notifications.send_push", return_value={"ok": True}):
            response = self.act(self.specialist, call, "accept")

        self.assertError(response, 409, "CALL_INVALID_STATE")
        call.refresh_from_db()
        self.assertEqual(call.status, Call.Status.MISSED)
        self.assertEqual(call.end_reason, "timeout")
        self.assertIsNone(call.answered_at)
        self.assertIn("call.missed", self.event_types(self.client_user))
        self.assertTrue(
            Notification.objects.filter(recipient=self.specialist, notification_type="missed_call").exists()
        )

        # в пределах таймаута + запаса принять можно
        ok = self.ring()
        Call.objects.filter(pk=ok.pk).update(created_at=timezone.now() - timedelta(seconds=50))
        self.assertEqual(self.act(self.specialist, ok, "accept").status_code, 200)


class ActiveCallTests(CallTestCase):
    URL = "/api/calls/active/"

    def get_active(self, user):
        self.auth(user)
        response = self.client.get(self.URL)
        self.assertEqual(response.status_code, 200, response.content)
        return response.json()

    def test_active_call_endpoint(self):
        self.activate_tariff()
        stranger = User.objects.create_user(username="stranger", password="pass", role=ROLE_SPECIALIST)

        empty = self.get_active(self.client_user)
        self.assertIsNone(empty["call"])
        self.assertIsNone(empty["token"])
        self.assertEqual(empty["livekitUrl"], "wss://rtc.example.com")

        call = self.ring()
        caller_view = self.get_active(self.client_user)
        self.assertEqual(caller_view["call"]["id"], str(call.pk))
        self.assertEqual(caller_view["call"]["status"], "ringing")
        self.assertEqual(caller_view["token"], "lk-token")
        callee_view = self.get_active(self.specialist)
        self.assertEqual(callee_view["call"]["id"], str(call.pk))
        self.assertIsNone(callee_view["token"])  # до ответа — только через accept/
        self.assertIsNone(self.get_active(stranger)["call"])  # чужой звонок не виден

        self.act(self.specialist, call, "accept")
        accepted = self.get_active(self.specialist)
        self.assertEqual(accepted["call"]["status"], "accepted")
        self.assertEqual(accepted["token"], "lk-token")
        self.livekit_mocks["access_token"].assert_called_with(self.specialist, call.room_name, video=False)
        self.assertIsNone(self.get_active(stranger)["call"])

        # зависший (дольше максимальной длительности) не считается активным
        Call.objects.filter(pk=call.pk).update(answered_at=timezone.now() - timedelta(hours=3))
        self.assertIsNone(self.get_active(self.client_user)["call"])

        # завершённый — тоже
        Call.objects.filter(pk=call.pk).update(answered_at=timezone.now())
        self.act(self.client_user, call, "end")
        self.assertIsNone(self.get_active(self.client_user)["call"])

        # зависший RINGING не отдаётся
        stale = self.ring()
        Call.objects.filter(pk=stale.pk).update(created_at=timezone.now() - timedelta(minutes=5))
        self.assertIsNone(self.get_active(self.specialist)["call"])


class LiveKitRoomsClientTests(SimpleTestCase):
    def test_existing_rooms_empty_names_skips_request(self):
        with patch("messenger.clients.livekit.asyncio.run") as run:
            self.assertEqual(livekit.existing_rooms([]), set())
        run.assert_not_called()

    @override_settings(**LIVEKIT_SETTINGS)
    def test_room_participants_identities_and_errors(self):
        from livekit.api import TwirpError

        def fake_run(result=None, error=None):
            def run(coro):
                coro.close()
                if error is not None:
                    raise error
                return result
            return run

        with patch("messenger.clients.livekit.asyncio.run", side_effect=fake_run(result={"1", "2"})):
            self.assertEqual(livekit.room_participants("call_x"), {"1", "2"})
        # комнаты уже нет — в ней никого
        with patch("messenger.clients.livekit.asyncio.run", side_effect=fake_run(error=TwirpError("not_found", "no room"))):
            self.assertEqual(livekit.room_participants("call_x"), set())
        for error in (TwirpError("unavailable", "down"), OSError("refused")):
            with patch("messenger.clients.livekit.asyncio.run", side_effect=fake_run(error=error)):
                with self.assertRaises(livekit.LiveKitError):
                    livekit.room_participants("call_x")

@override_settings(CELERY_TASK_ALWAYS_EAGER=True, **LIVEKIT_SETTINGS)
class ConcurrentStartTests(TransactionTestCase):
    """Два одновременных звонка одному специалисту: звонит только один, второй — busy."""

    def setUp(self):
        for target, kwargs in (
            ("account.models.User.upsert_stream_user", {}),
            ("chat_access.services.chat_commands.create_stream_channel", {}),
            ("messenger.clients.centrifugo.broadcast", {}),
            ("messenger.clients.livekit.access_token", {"return_value": "lk-token"}),
            # окно гонки: создание комнаты «долгое», пока держится лок
            ("messenger.clients.livekit.create_room", {"side_effect": lambda name: time.sleep(0.3)}),
            ("messenger.tasks.expire_call.apply_async", {}),
            ("messenger.tasks.send_call_push.delay", {}),
        ):
            patcher = patch(target, **kwargs)
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_simultaneous_starts_do_not_both_ring(self):
        from messenger.services import calls

        specialist = User.objects.create_user(username="spec_race", password="pass", role=ROLE_SPECIALIST)
        chats = []
        for index in range(2):
            client = User.objects.create_user(username=f"client_race_{index}", password="pass", role=ROLE_CLIENT)
            chat = create_or_get_chat(client, specialist)
            activate_tariff(chat)
            chats.append((chat, client))

        barrier = threading.Barrier(2)
        results, errors = [], []

        def worker(chat, client):
            try:
                barrier.wait()
                call, _ = calls.start_call(chat, client, Call.Kind.AUDIO)
                results.append(call.status)
            except Exception as exc:  # pragma: no cover - диагностика
                errors.append(exc)
            finally:
                connection.close()

        threads = [threading.Thread(target=worker, args=pair) for pair in chats]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        self.assertEqual(errors, [])
        self.assertEqual(sorted(results), [Call.Status.BUSY, Call.Status.RINGING])
