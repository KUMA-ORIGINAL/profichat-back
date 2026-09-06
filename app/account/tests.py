from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from account.models import (
    Application,
    ApplicationEducation,
    Notification,
    UserEducation,
    UserWorkplace,
    WorkExperience,
)
from account.services.application_review import apply_approval_effects
from common.notifications import notify_user

User = get_user_model()


class UserProfileHistoryApiTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="profile_user", password="pass")
        self.client.force_authenticate(user=self.user)

    @patch("account.views.user.broadcast_user_update")
    def test_patch_replaces_education_and_workplace_lists(self, broadcast_mock):
        response = self.client.patch(
            reverse("user-me"),
            data={
                "education": [{
                    "institution": "БГУ",
                    "faculty": "Юридический",
                    "start_date": "2018-09-01",
                    "end_date": "2022-06-30",
                }],
                "work_experience": [{
                    "organization": "МЦ Мама Доктор",
                    "position": "Ортодонт",
                    "start_date": "2022-07-01",
                    "end_date": None,
                    "is_current": True,
                }],
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertEqual(UserEducation.objects.get(user=self.user).faculty, "Юридический")
        workplace = UserWorkplace.objects.get(user=self.user)
        self.assertEqual(workplace.position, "Ортодонт")
        self.assertTrue(workplace.is_current)
        self.assertIsNone(workplace.end_date)
        self.assertEqual(response.data["education"][0]["institution"], "БГУ")
        self.assertEqual(response.data["work_experience"][0]["organization"], "МЦ Мама Доктор")
        broadcast_mock.assert_called_once()

    @patch("account.views.user.broadcast_user_update")
    def test_patch_omitted_list_is_preserved_and_empty_list_clears(self, _broadcast_mock):
        UserEducation.objects.create(
            user=self.user,
            institution="КГМА",
            start_date="2010-09-01",
            end_date="2016-06-30",
        )
        UserWorkplace.objects.create(
            user=self.user,
            organization="Клиника",
            start_date="2020-01-01",
            is_current=True,
        )

        first_response = self.client.patch(
            reverse("user-me"), data={"education": []}, format="json"
        )
        self.assertEqual(first_response.status_code, status.HTTP_200_OK)
        self.assertFalse(self.user.educations.exists())
        self.assertTrue(self.user.workplaces.exists())

    @patch("account.views.user.broadcast_user_update")
    def test_rejects_invalid_work_period(self, broadcast_mock):
        response = self.client.patch(
            reverse("user-me"),
            data={
                "work_experience": [{
                    "organization": "Клиника",
                    "position": "Врач",
                    "start_date": "2024-01-01",
                    "end_date": "2023-01-01",
                    "is_current": False,
                }],
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(self.user.workplaces.exists())
        broadcast_mock.assert_not_called()


class ApplicationProfileHistoryApiTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="applicant", password="pass")
        self.client.force_authenticate(user=self.user)

    @patch("common.telegram_notifier.notify_specialist_application")
    def test_application_accepts_structured_history(self, notify_mock):
        response = self.client.post(
            reverse("application-create-list"),
            data={
                "first_name": "Айгуль",
                "last_name": "Осмонова",
                "custom_profession": "Ортодонт",
                "education": [{
                    "institution": "КГМА",
                    "faculty": "Стоматология",
                    "start_date": "2014-09-01",
                    "end_date": "2020-06-30",
                }],
                "work_experiences": [{
                    "organization": "МЦ Мама Доктор",
                    "position": "Ортодонт",
                    "start_date": "2020-07-01",
                    "end_date": None,
                    "is_current": True,
                }],
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        self.assertEqual(ApplicationEducation.objects.get().institution, "КГМА")
        self.assertEqual(WorkExperience.objects.get().position, "Ортодонт")
        notify_mock.assert_called_once()

    def test_approved_application_copies_history_to_empty_profile(self):
        application = Application.objects.create(
            user=self.user,
            first_name="Айгуль",
            last_name="Осмонова",
            custom_profession="Ортодонт",
        )
        ApplicationEducation.objects.create(
            application=application,
            institution="КГМА",
            faculty="Стоматология",
            start_date="2014-09-01",
            end_date="2020-06-30",
        )
        WorkExperience.objects.create(
            application=application,
            organization="МЦ Мама Доктор",
            position="Ортодонт",
            start_date="2020-07-01",
            is_current=True,
        )

        apply_approval_effects(application)

        self.assertEqual(self.user.educations.get().institution, "КГМА")
        self.assertEqual(self.user.workplaces.get().organization, "МЦ Мама Доктор")


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
        # notify_user докладывает в payload источник и тип: приложению нужно понять,
        # своё это уведомление или из ErkinAI, и в pushе ленты нет.
        self.assertEqual(
            notification.payload,
            {"k": "v", "source": "profichat", "type": Notification.TYPE_SYSTEM},
        )
        self.assertIsNotNone(notification.pushed_at)
