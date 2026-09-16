from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from account.models import (
    ROLE_SPECIALIST,
    Application,
    ApplicationEducation,
    Notification,
    ProfessionCategory,
    ProfessionRequest,
    UserEducation,
    UserWorkplace,
    WorkExperience,
    WorkSchedule,
)
from account.serializers import WorkScheduleSerializer
from account.services.application_review import apply_approval_effects
from account.services.profession_request import (
    ProfessionRequestAlreadyReviewed,
    approve_profession_request,
    reject_profession_request,
)
from common.notifications import notify_user, send_profession_request_approved_push

User = get_user_model()


class WorkScheduleSerializerTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="schedule_user", password="pass")

    def test_accepts_lunch_inside_working_hours(self):
        serializer = WorkScheduleSerializer(
            data={
                "day_of_week": 1,
                "from_time": "09:00:00",
                "to_time": "18:00:00",
                "lunch_from_time": "13:00:00",
                "lunch_to_time": "14:00:00",
            },
            context={"request": type("Request", (), {"user": self.user})()},
        )

        self.assertTrue(serializer.is_valid(), serializer.errors)

    def test_rejects_incomplete_lunch_period(self):
        serializer = WorkScheduleSerializer(
            data={
                "day_of_week": 1,
                "from_time": "09:00:00",
                "to_time": "18:00:00",
                "lunch_from_time": "13:00:00",
            },
            context={"request": type("Request", (), {"user": self.user})()},
        )

        self.assertFalse(serializer.is_valid())

    def test_rejects_lunch_outside_working_hours(self):
        serializer = WorkScheduleSerializer(
            data={
                "day_of_week": 1,
                "from_time": "09:00:00",
                "to_time": "18:00:00",
                "lunch_from_time": "18:00:00",
                "lunch_to_time": "19:00:00",
            },
            context={"request": type("Request", (), {"user": self.user})()},
        )

        self.assertFalse(serializer.is_valid())

    def test_day_off_clears_lunch_period(self):
        schedule = WorkSchedule.objects.create(
            user=self.user,
            day_of_week=1,
            from_time="09:00:00",
            to_time="18:00:00",
            lunch_from_time="13:00:00",
            lunch_to_time="14:00:00",
        )
        serializer = WorkScheduleSerializer(schedule, data={"is_day_off": True}, partial=True)

        self.assertTrue(serializer.is_valid(), serializer.errors)
        updated = serializer.save()
        self.assertIsNone(updated.lunch_from_time)
        self.assertIsNone(updated.lunch_to_time)


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


APPLICATION_HISTORY = {
    "education": [{
        "institution": "КГМА",
        "faculty": "Стоматология",
        "start_date": "2014-09-01",
        "end_date": "2020-06-30",
    }],
    "work_experiences": [{
        "organization": "МЦ Мама Доктор",
        "position": "Кинолог",
        "start_date": "2020-07-01",
        "end_date": None,
        "is_current": True,
    }],
}


@patch("common.telegram_notifier.notify_specialist_application")
class ApplicationCustomProfessionApiTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="applicant_2", password="pass")
        self.client.force_authenticate(user=self.user)

    def _apply(self, **extra):
        return self.client.post(
            reverse("application-create-list"),
            data={"first_name": "Дастан", "last_name": "Азимжанов", **APPLICATION_HISTORY, **extra},
            format="json",
        )

    def test_description_is_saved_and_queued_for_moderation(self, notify_mock):
        response = self._apply(
            custom_profession="  Кинолог ",
            custom_profession_description="Специалист по дрессировке собак",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        application = Application.objects.get()
        self.assertEqual(application.custom_profession, "Кинолог")
        self.assertEqual(application.custom_profession_description, "Специалист по дрессировке собак")

        profession_request = application.profession_request
        self.assertEqual(profession_request.source, ProfessionRequest.SOURCE_APPLICATION)
        self.assertEqual(profession_request.status, ProfessionRequest.STATUS_PENDING)
        self.assertEqual(profession_request.user, self.user)
        self.assertEqual(profession_request.description, "Специалист по дрессировке собак")

    def test_custom_profession_without_description_still_accepted(self, notify_mock):
        response = self._apply(custom_profession="Кинолог")

        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        self.assertEqual(Application.objects.get().custom_profession_description, "")
        self.assertEqual(ProfessionRequest.objects.get().description, "")

    def test_description_without_custom_profession_is_dropped(self, notify_mock):
        category = ProfessionCategory.objects.create(name="Разработчик")

        response = self._apply(profession=category.id, custom_profession_description="лишнее")

        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        self.assertEqual(Application.objects.get().custom_profession_description, "")
        self.assertFalse(ProfessionRequest.objects.exists())

    def test_too_long_description_is_rejected(self, notify_mock):
        response = self._apply(custom_profession="Кинолог", custom_profession_description="x" * 501)

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["code"], "VALIDATION_ERROR")
        self.assertIn("custom_profession_description", response.data["errors"])


# throttle считает запросы в кэше — в тестах он в памяти, а не в Redis
@override_settings(CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}})
@patch("common.telegram_notifier.notify_profession_request")
class ProfessionRequestApiTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="requester", password="pass")
        self.client.force_authenticate(user=self.user)
        self.url = reverse("profession-requests-list")
        self.payload = {
            "name": "Кинолог",
            "description": "Кинолог — это специалист, который занимается дрессировкой собак",
        }

    def test_creates_pending_request(self, notify_mock):
        response = self.client.post(self.url, data=self.payload, format="json")

        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        self.assertEqual(response.data["status"], "pending")
        self.assertEqual(response.data["name"], "Кинолог")
        self.assertIsNone(response.data["profession_category"])
        self.assertIn("created_at", response.data)

        profession_request = ProfessionRequest.objects.get()
        self.assertEqual(profession_request.user, self.user)
        self.assertEqual(profession_request.source, ProfessionRequest.SOURCE_PROFILE)
        notify_mock.assert_called_once()

    def test_requires_authentication(self, notify_mock):
        self.client.force_authenticate(user=None)

        response = self.client.post(self.url, data=self.payload, format="json")

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(response.data["code"], "NOT_AUTHENTICATED")

    def test_validates_required_fields_and_limits(self, notify_mock):
        response = self.client.post(self.url, data={"name": "   ", "description": "x" * 501}, format="json")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["code"], "VALIDATION_ERROR")
        self.assertIn("name", response.data["errors"])
        self.assertIn("description", response.data["errors"])
        self.assertFalse(ProfessionRequest.objects.exists())

        response = self.client.post(self.url, data={"name": "x" * 101, "description": "ok"}, format="json")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("name", response.data["errors"])

    def test_conflict_when_category_already_exists(self, notify_mock):
        ProfessionCategory.objects.create(name="кинолог")

        response = self.client.post(self.url, data=self.payload, format="json")

        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(response.data["code"], "CONFLICT")
        self.assertIn("уже есть в списке", response.data["message"])
        self.assertFalse(ProfessionRequest.objects.exists())

    def test_conflict_when_own_pending_request_exists(self, notify_mock):
        ProfessionRequest.objects.create(user=self.user, name="КИНОЛОГ", description="…")

        response = self.client.post(self.url, data=self.payload, format="json")

        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(response.data["code"], "CONFLICT")
        self.assertEqual(response.data["message"], "Заявка на эту профессию уже на проверке")
        self.assertEqual(ProfessionRequest.objects.count(), 1)

    def test_rejected_request_can_be_resubmitted(self, notify_mock):
        ProfessionRequest.objects.create(
            user=self.user, name="Кинолог", description="…", status=ProfessionRequest.STATUS_REJECTED,
        )

        response = self.client.post(self.url, data=self.payload, format="json")

        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        self.assertEqual(ProfessionRequest.objects.count(), 2)

    def test_list_returns_only_own_requests(self, notify_mock):
        other = User.objects.create_user(username="other_requester", password="pass")
        ProfessionRequest.objects.create(user=self.user, name="Кинолог", description="…")
        ProfessionRequest.objects.create(user=other, name="Флорист", description="…")

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual([item["name"] for item in response.data], ["Кинолог"])


class ProfessionRequestModerationTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="moderated", password="pass")

    def _request(self, **kwargs):
        return ProfessionRequest.objects.create(user=self.user, name="Кинолог", description="…", **kwargs)

    @patch("account.services.profession_request.send_profession_request_approved_push")
    def test_approval_creates_category_and_assigns_it_to_specialist(self, push_mock):
        self.user.role = ROLE_SPECIALIST
        self.user.save()
        profession_request = self._request()

        with self.captureOnCommitCallbacks(execute=True):
            approve_profession_request(profession_request, reviewed_by="tester")

        profession_request.refresh_from_db()
        self.user.refresh_from_db()
        category = ProfessionCategory.objects.get(name="Кинолог")
        self.assertEqual(profession_request.status, ProfessionRequest.STATUS_APPROVED)
        self.assertEqual(profession_request.profession_category, category)
        self.assertIsNotNone(profession_request.reviewed_at)
        self.assertEqual(self.user.profession, category)
        push_mock.assert_called_once_with(self.user, profession_request)

    @patch("account.services.profession_request.send_profession_request_approved_push")
    def test_approval_does_not_touch_client_profile(self, push_mock):
        profession_request = self._request()

        with self.captureOnCommitCallbacks(execute=True):
            approve_profession_request(profession_request)

        self.user.refresh_from_db()
        self.assertIsNone(self.user.profession)
        self.assertTrue(ProfessionCategory.objects.filter(name="Кинолог").exists())

    @patch("account.services.profession_request.send_profession_request_approved_push")
    def test_approval_reuses_category_chosen_by_moderator(self, push_mock):
        category = ProfessionCategory.objects.create(name="Дрессировщик")
        profession_request = self._request()

        approve_profession_request(profession_request, category=category)

        profession_request.refresh_from_db()
        self.assertEqual(profession_request.profession_category, category)
        self.assertFalse(ProfessionCategory.objects.filter(name="Кинолог").exists())

    @patch("account.services.profession_request.send_profession_request_approved_push")
    def test_approval_fills_pending_application_then_profile_on_accept(self, push_mock):
        application = Application.objects.create(
            user=self.user, first_name="Д", last_name="А", custom_profession="Кинолог",
        )
        profession_request = self._request(
            source=ProfessionRequest.SOURCE_APPLICATION, application=application,
        )

        approve_profession_request(profession_request)

        application.refresh_from_db()
        self.user.refresh_from_db()
        category = ProfessionCategory.objects.get(name="Кинолог")
        self.assertEqual(application.profession, category)
        self.assertIsNone(self.user.profession)

        application.status = "accepted"
        application.save()
        apply_approval_effects(application)

        self.user.refresh_from_db()
        self.assertEqual(self.user.role, ROLE_SPECIALIST)
        self.assertEqual(self.user.profession, category)

    @patch("account.services.profession_request.send_profession_request_approved_push")
    def test_approval_after_accepted_application_sets_profile_profession(self, push_mock):
        application = Application.objects.create(
            user=self.user, first_name="Д", last_name="А", custom_profession="Кинолог", status="accepted",
        )
        profession_request = self._request(
            source=ProfessionRequest.SOURCE_APPLICATION, application=application,
        )

        approve_profession_request(profession_request)

        self.user.refresh_from_db()
        self.assertEqual(self.user.profession, ProfessionCategory.objects.get(name="Кинолог"))

    @patch("account.services.profession_request.send_profession_request_rejected_push")
    def test_rejection_stores_reason_and_notifies(self, push_mock):
        profession_request = self._request()

        with self.captureOnCommitCallbacks(execute=True):
            reject_profession_request(profession_request, reason="Слишком общее название")

        profession_request.refresh_from_db()
        self.assertEqual(profession_request.status, ProfessionRequest.STATUS_REJECTED)
        self.assertEqual(profession_request.reason, "Слишком общее название")
        self.assertFalse(ProfessionCategory.objects.exists())
        push_mock.assert_called_once_with(self.user, profession_request)

    def test_second_decision_is_refused(self):
        profession_request = self._request(status=ProfessionRequest.STATUS_REJECTED)

        with self.assertRaises(ProfessionRequestAlreadyReviewed):
            approve_profession_request(profession_request)

    def test_approved_push_creates_notification(self):
        category = ProfessionCategory.objects.create(name="Кинолог")
        profession_request = self._request(
            status=ProfessionRequest.STATUS_APPROVED, profession_category=category,
        )

        with patch("common.notifications.send_push", return_value={"ok": False}):
            send_profession_request_approved_push(self.user, profession_request)

        notification = Notification.objects.get(recipient=self.user)
        self.assertEqual(notification.notification_type, Notification.TYPE_PROFESSION_REQUEST_APPROVED)
        self.assertEqual(notification.payload["profession_category_id"], str(category.id))
        self.assertEqual(notification.payload["source"], Notification.SOURCE_PROFICHAT)


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
