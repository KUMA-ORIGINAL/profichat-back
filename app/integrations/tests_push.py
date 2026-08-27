from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import override_settings
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from account.models import ROLE_CLIENT, Notification

User = get_user_model()

_API_KEY = "erkinai-test-key"


# Ключ сохранил историческое имя MEDCRM_API_KEY: тот же секрет уже используют
# легаси-эндпоинты /api/integration/medcrm/*.
@override_settings(MEDCRM_API_KEY=_API_KEY)
class ErkinAIPushTests(APITestCase):
    def setUp(self):
        self.chat_client_patcher = patch("account.models.user.chat_client")
        self.chat_client_patcher.start()
        self.addCleanup(self.chat_client_patcher.stop)

        self.user = User.objects.create_user(
            username="push_user",
            phone_number="+996555111222",
            first_name="A",
            last_name="B",
            role=ROLE_CLIENT,
            password="pass",
        )
        self.url = reverse("integrations:erkinai-push")

    def _post(self, payload, api_key=_API_KEY):
        headers = {"HTTP_X_API_KEY": api_key} if api_key else {}
        return self.client.post(self.url, payload, format="json", **headers)

    def _payload(self, **overrides):
        body = {
            "phone_number": "+996555111222",
            "title": "Запись подтверждена",
            "body": "Ждём вас завтра в 10:00.",
        }
        body.update(overrides)
        return body

    def test_requires_api_key(self):
        response = self._post(self._payload(), api_key=None)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_rejects_wrong_api_key(self):
        response = self._post(self._payload(), api_key="nope")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    @patch("integrations.views.push.notify_user")
    def test_creates_notification_and_sends_push(self, notify_user):
        notify_user.return_value = {
            "ok": True,
            "notification_id": 7,
            "device_count": 2,
            "success_count": 1,
            "error_code": "",
            "error_message": "",
        }

        response = self._post(
            self._payload(payload={"appointment_id": 42}, external_id="job-1"),
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data["delivered"])
        self.assertEqual(response.data["notification_id"], 7)
        self.assertFalse(response.data["duplicate"])

        kwargs = notify_user.call_args.kwargs
        self.assertEqual(kwargs["user"], self.user)
        self.assertEqual(kwargs["title"], "Запись подтверждена")
        self.assertEqual(kwargs["notification_type"], Notification.TYPE_ERKINAI)
        # FCM data принимает только строки — числа из ErkinAI приводятся здесь,
        # иначе отправка упала бы уже внутри firebase_admin.
        self.assertEqual(kwargs["payload"]["appointment_id"], "42")
        self.assertEqual(kwargs["payload"]["external_id"], "job-1")

    @patch("integrations.views.push.notify_user")
    def test_reports_undelivered_push_with_200(self, notify_user):
        """Нет устройства — это факт о получателе, а не отказ запроса."""
        notify_user.return_value = {
            "ok": False,
            "notification_id": 8,
            "device_count": 0,
            "success_count": 0,
            "error_code": "NO_DEVICES",
            "error_message": "Нет активных устройств",
        }

        response = self._post(self._payload())

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(response.data["delivered"])
        self.assertEqual(response.data["error_code"], "NO_DEVICES")

    def test_unknown_phone_is_404_and_creates_no_account(self):
        response = self._post(self._payload(phone_number="+996555999888"))

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(response.data["code"], "USER_NOT_FOUND")
        self.assertEqual(User.objects.count(), 1)

    @patch("integrations.views.push.notify_user")
    def test_matches_phone_written_without_plus(self, notify_user):
        notify_user.return_value = {
            "ok": True,
            "notification_id": 9,
            "device_count": 1,
            "success_count": 1,
            "error_code": "",
            "error_message": "",
        }

        response = self._post(self._payload(phone_number="996 555 111 222"))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(notify_user.call_args.kwargs["user"], self.user)

    @patch("integrations.views.push.notify_user")
    def test_repeat_with_same_external_id_does_not_push_twice(self, notify_user):
        notify_user.return_value = {
            "ok": True,
            "notification_id": 10,
            "device_count": 1,
            "success_count": 1,
            "error_code": "",
            "error_message": "",
        }
        Notification.objects.create(
            recipient=self.user,
            notification_type=Notification.TYPE_ERKINAI,
            title="Запись подтверждена",
            message="Ждём вас завтра в 10:00.",
            payload={"external_id": "job-2"},
        )

        response = self._post(self._payload(external_id="job-2"))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data["duplicate"])
        notify_user.assert_not_called()
        self.assertEqual(Notification.objects.count(), 1)

    def test_rejects_blank_body(self):
        response = self._post(self._payload(body="   "))
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
