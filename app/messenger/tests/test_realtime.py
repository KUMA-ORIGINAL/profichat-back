from unittest.mock import MagicMock, patch

import jwt
import requests
from django.contrib.auth import get_user_model
from django.test import override_settings
from django.utils import timezone

from account.models import ROLE_CLIENT
from messenger.clients import centrifugo
from messenger.clients.centrifugo import CentrifugoError
from messenger.services import events
from messenger.tests.base import MessengerTestCase

User = get_user_model()

SECRET = "x" * 40
# Оригинальная функция: MessengerTestCase подменяет centrifugo.broadcast на мок в setUp.
REAL_BROADCAST = centrifugo.broadcast


@override_settings(CENTRIFUGO_TOKEN_SECRET=SECRET, CENTRIFUGO_WS_URL="wss://example.test/connection/websocket")
class TokenTests(MessengerTestCase):
    def test_connection_token_contains_personal_channel(self):
        self.auth(self.client_user)
        response = self.client.get("/api/messenger/connection-token/")
        self.assertEqual(response.status_code, 200)
        payload = jwt.decode(response.data["token"], SECRET, algorithms=["HS256"])
        self.assertEqual(payload["sub"], str(self.client_user.id))
        self.assertEqual(payload["channels"], [f"personal:{self.client_user.id}"])
        expected = timezone.now().timestamp() + 3600
        self.assertAlmostEqual(payload["exp"], expected, delta=10)
        self.assertEqual(response.json()["wsUrl"], "wss://example.test/connection/websocket")
        self.assertIn("expiresAt", response.json())

    @override_settings(
        MESSENGER_MAX_ATTACHMENTS_PER_MESSAGE=7,
        MESSENGER_ATTACHMENT_MAX_BYTES={"image": 1, "video": 2, "file": 3, "voice": 4},
    )
    def test_connection_token_includes_upload_limits(self):
        self.auth(self.client_user)
        response = self.client.get("/api/messenger/connection-token/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json()["limits"],
            {
                "imageMaxBytes": 1,
                "videoMaxBytes": 2,
                "fileMaxBytes": 3,
                "voiceMaxBytes": 4,
                "maxAttachmentsPerMessage": 7,
            },
        )

    def test_connection_token_requires_auth(self):
        response = self.client.get("/api/messenger/connection-token/")
        self.assertEqual(response.status_code, 401)

    def test_subscription_token_for_member(self):
        self.auth(self.client_user)
        response = self.client.get(f"/api/chats/{self.chat.channel_id}/subscription-token/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["channel"], f"chat:{self.chat.channel_id}")
        payload = jwt.decode(response.json()["token"], SECRET, algorithms=["HS256"])
        self.assertEqual(payload["sub"], str(self.client_user.id))
        self.assertEqual(payload["channel"], f"chat:{self.chat.channel_id}")

    def test_subscription_token_requires_membership(self):
        stranger = User.objects.create_user(username="stranger", password="pass", role=ROLE_CLIENT)
        self.auth(stranger)
        response = self.client.get(f"/api/chats/{self.chat.channel_id}/subscription-token/")
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["code"], "CHAT_NOT_FOUND")

    @override_settings(CENTRIFUGO_TOKEN_SECRET="")
    def test_tokens_unavailable_without_secret(self):
        self.auth(self.client_user)
        response = self.client.get("/api/messenger/connection-token/")
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["code"], "REALTIME_UNAVAILABLE")


class PublishTests(MessengerTestCase):
    def test_personal_channel(self):
        self.assertEqual(events.personal_channel(5), "personal:5")

    def test_publish_sends_after_commit_with_camelized_envelope(self):
        with self.captureOnCommitCallbacks(execute=True) as callbacks:
            events.publish([1, 2], "message.new", {"channel_id": "chat_1_2"})
            self.broadcast_mock.assert_not_called()
        self.assertEqual(len(callbacks), 1)
        self.broadcast_mock.assert_called_once_with(
            ["personal:1", "personal:2"],
            {"type": "message.new", "data": {"channelId": "chat_1_2"}},
        )

    def test_publish_without_users_does_nothing(self):
        with self.captureOnCommitCallbacks(execute=True) as callbacks:
            events.publish([], "message.new", {})
        self.assertEqual(callbacks, [])
        self.broadcast_mock.assert_not_called()

    def test_publish_failure_schedules_retry(self):
        self.broadcast_mock.side_effect = CentrifugoError("boom")
        with patch("messenger.tasks.publish_event.apply_async") as apply_async:
            with self.captureOnCommitCallbacks(execute=True):
                events.publish([1], "message.new", {"channel_id": "c"})
        apply_async.assert_called_once_with(
            args=[["personal:1"], {"type": "message.new", "data": {"channelId": "c"}}],
            countdown=2,
        )

    def test_publish_event_task_broadcasts(self):
        from messenger.tasks import publish_event

        publish_event.apply(args=[["personal:1"], {"type": "t", "data": {}}]).get()
        self.broadcast_mock.assert_called_once_with(["personal:1"], {"type": "t", "data": {}})

    def test_publish_event_task_retry_policy(self):
        from messenger.tasks import publish_event

        self.assertEqual(publish_event.max_retries, 5)
        self.assertIn(CentrifugoError, publish_event.autoretry_for)


@override_settings(
    CENTRIFUGO_API_URL="http://centrifugo:8000/api", CENTRIFUGO_API_KEY="key123", CENTRIFUGO_TOKEN_SECRET=SECRET
)
class ClientTests(MessengerTestCase):
    def setUp(self):
        super().setUp()
        patcher = patch("messenger.clients.centrifugo.broadcast", REAL_BROADCAST)
        patcher.start()
        self.addCleanup(patcher.stop)

    @staticmethod
    def _response(status_code=200, body=None):
        response = MagicMock(status_code=status_code, text="err")
        response.json.return_value = {} if body is None else body
        return response

    def test_broadcast_posts_with_api_key(self):
        with patch("messenger.clients.centrifugo.requests.post", return_value=self._response()) as post:
            centrifugo.broadcast(["personal:1"], {"a": 1})
        args, kwargs = post.call_args
        self.assertEqual(args[0], "http://centrifugo:8000/api/broadcast")
        self.assertEqual(kwargs["headers"]["X-API-Key"], "key123")
        self.assertEqual(kwargs["json"], {"channels": ["personal:1"], "data": {"a": 1}})
        self.assertEqual(kwargs["timeout"], 3)

    def test_broadcast_raises_on_non_2xx(self):
        with patch("messenger.clients.centrifugo.requests.post", return_value=self._response(500)):
            with self.assertRaises(CentrifugoError):
                centrifugo.broadcast(["personal:1"], {})

    def test_broadcast_raises_on_network_error(self):
        with patch("messenger.clients.centrifugo.requests.post", side_effect=requests.ConnectionError("x")):
            with self.assertRaises(CentrifugoError):
                centrifugo.broadcast(["personal:1"], {})

    def test_broadcast_raises_on_error_in_body(self):
        # Centrifugo HTTP API отвечает 200 с {"error": {...}} при ошибках уровня API
        body = {"error": {"code": 100, "message": "internal"}}
        with patch("messenger.clients.centrifugo.requests.post", return_value=self._response(200, body)):
            with self.assertRaises(CentrifugoError):
                centrifugo.broadcast(["personal:1"], {})

    def test_subscription_token_claims(self):
        token = centrifugo.subscription_token(7, "chat:abc")
        payload = jwt.decode(token, SECRET, algorithms=["HS256"])
        self.assertEqual(payload["sub"], "7")
        self.assertEqual(payload["channel"], "chat:abc")
        self.assertIn("exp", payload)
