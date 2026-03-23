from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from account.models import Notification
from common.notifications import notify_user

User = get_user_model()


class NotificationApiTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="user_1", password="pass")
        self.other_user = User.objects.create_user(username="user_2", password="pass")
        self.client.force_authenticate(user=self.user)

    def test_list_returns_only_current_user_notifications(self):
        Notification.objects.create(
            recipient=self.user,
            notification_type=Notification.TYPE_SYSTEM,
            title="Mine",
            message="Visible",
        )
        Notification.objects.create(
            recipient=self.other_user,
            notification_type=Notification.TYPE_SYSTEM,
            title="Other",
            message="Hidden",
        )

        response = self.client.get(reverse("notifications-list"))
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        results = response.data["results"]
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["title"], "Mine")

    def test_unread_count_endpoint(self):
        Notification.objects.create(
            recipient=self.user,
            notification_type=Notification.TYPE_SYSTEM,
            title="N1",
            message="M1",
            is_read=False,
        )
        Notification.objects.create(
            recipient=self.user,
            notification_type=Notification.TYPE_SYSTEM,
            title="N2",
            message="M2",
            is_read=True,
            read_at=timezone.now(),
        )

        response = self.client.get(reverse("notifications-unread-count"))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["unread_count"], 1)

    def test_mark_single_notification_as_read(self):
        notification = Notification.objects.create(
            recipient=self.user,
            notification_type=Notification.TYPE_SYSTEM,
            title="N1",
            message="M1",
            is_read=False,
        )

        response = self.client.post(reverse("notifications-mark-read", kwargs={"pk": notification.id}))
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        notification.refresh_from_db()
        self.assertTrue(notification.is_read)
        self.assertIsNotNone(notification.read_at)

    def test_mark_bulk_notifications_as_read(self):
        first = Notification.objects.create(
            recipient=self.user,
            notification_type=Notification.TYPE_SYSTEM,
            title="N1",
            message="M1",
        )
        second = Notification.objects.create(
            recipient=self.user,
            notification_type=Notification.TYPE_SYSTEM,
            title="N2",
            message="M2",
        )
        foreign = Notification.objects.create(
            recipient=self.other_user,
            notification_type=Notification.TYPE_SYSTEM,
            title="N3",
            message="M3",
        )

        response = self.client.post(
            reverse("notifications-mark-read-bulk"),
            data={"notification_ids": [first.id, second.id, foreign.id]},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["updated_count"], 2)

        first.refresh_from_db()
        second.refresh_from_db()
        foreign.refresh_from_db()
        self.assertTrue(first.is_read)
        self.assertTrue(second.is_read)
        self.assertFalse(foreign.is_read)


class NotifyUserServiceTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="notify_user", password="pass")

    @patch("common.notifications.send_push")
    def test_notify_user_creates_notification_and_sets_pushed_at(self, send_push_mock):
        send_push_mock.return_value = {
            "ok": True,
            "success_count": 1,
            "device_count": 1,
            "error_message": "",
        }

        result = notify_user(
            user=self.user,
            title="Test title",
            message="Test body",
            notification_type=Notification.TYPE_SYSTEM,
            payload={"k": "v"},
            return_meta=True,
        )

        self.assertTrue(result["ok"])
        self.assertIn("notification_id", result)

        notification = Notification.objects.get(id=result["notification_id"])
        self.assertEqual(notification.recipient_id, self.user.id)
        self.assertEqual(notification.payload, {"k": "v"})
        self.assertIsNotNone(notification.pushed_at)
