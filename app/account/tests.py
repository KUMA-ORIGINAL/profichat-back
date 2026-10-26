import importlib
from datetime import datetime, time, timedelta
from unittest.mock import MagicMock, patch

from django.apps import apps as django_apps
from django.contrib.auth import get_user_model
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from push_notifications.models import GCMDevice
from rest_framework.test import APITestCase

from account.models import (
    ROLE_SPECIALIST,
    Application,
    ApplicationEducation,
    NonWorkingDate,
    Notification,
    PushDeviceStatus,
    ProfessionCategory,
    ProfessionRequest,
    UserEducation,
    UserWorkplace,
    WorkExperience,
    WorkSchedule,
)
from account.models import QuietHoursState
from account.serializers import WorkScheduleSerializer
from account.services.quiet_hours import quiet_until, summary_text, sync_quiet_hours
from chat_access.models import AccessOrder, Tariff
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


class NonWorkingDateApiTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="days_off_user", password="pass")
        self.other = User.objects.create_user(username="days_off_other", password="pass")
        self.client.force_authenticate(user=self.user)
        self.today = timezone.localdate()

    def day(self, offset):
        return self.today + timedelta(days=offset)

    @patch("account.views.non_working_date.broadcast_user_update")
    def test_create_is_idempotent(self, broadcast_mock):
        url = reverse("non-working-date-list")
        first = self.client.post(url, {"date": self.day(3).isoformat()}, format="json")
        second = self.client.post(url, {"date": self.day(3).isoformat()}, format="json")

        self.assertEqual(first.status_code, status.HTTP_201_CREATED)
        self.assertEqual(second.status_code, status.HTTP_200_OK)
        self.assertEqual(first.data["id"], second.data["id"])
        self.assertEqual(NonWorkingDate.objects.filter(user=self.user).count(), 1)
        broadcast_mock.assert_called_once()

    def test_rejects_past_and_too_far_dates(self):
        url = reverse("non-working-date-list")
        past = self.client.post(url, {"date": self.day(-1).isoformat()}, format="json")
        far = self.client.post(url, {"date": self.day(400).isoformat()}, format="json")

        self.assertEqual(past.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(far.status_code, status.HTTP_400_BAD_REQUEST)

    def test_list_returns_only_own_upcoming_dates(self):
        NonWorkingDate.objects.create(user=self.user, date=self.day(-2))
        NonWorkingDate.objects.create(user=self.user, date=self.day(0))
        NonWorkingDate.objects.create(user=self.user, date=self.day(5))
        NonWorkingDate.objects.create(user=self.other, date=self.day(1))

        response = self.client.get(reverse("non-working-date-list"))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            [item["date"] for item in response.data],
            [self.day(0).isoformat(), self.day(5).isoformat()],
        )

    @patch("account.views.non_working_date.broadcast_user_update")
    def test_sync_replaces_upcoming_dates_and_keeps_past(self, broadcast_mock):
        NonWorkingDate.objects.create(user=self.user, date=self.day(-3))
        NonWorkingDate.objects.create(user=self.user, date=self.day(1))
        NonWorkingDate.objects.create(user=self.user, date=self.day(2))

        response = self.client.put(
            reverse("non-working-date-sync"),
            {"dates": [self.day(4).isoformat(), self.day(2).isoformat(), self.day(4).isoformat()]},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertEqual(
            [item["date"] for item in response.data],
            [self.day(2).isoformat(), self.day(4).isoformat()],
        )
        self.assertEqual(
            list(NonWorkingDate.objects.filter(user=self.user).values_list("date", flat=True)),
            [self.day(-3), self.day(2), self.day(4)],
        )
        broadcast_mock.assert_called_once()

    @patch("account.views.non_working_date.broadcast_user_update")
    def test_delete_own_date_only(self, broadcast_mock):
        own = NonWorkingDate.objects.create(user=self.user, date=self.day(1))
        foreign = NonWorkingDate.objects.create(user=self.other, date=self.day(1))

        foreign_response = self.client.delete(reverse("non-working-date-detail", args=[foreign.id]))
        own_response = self.client.delete(reverse("non-working-date-detail", args=[own.id]))

        self.assertEqual(foreign_response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(own_response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertTrue(NonWorkingDate.objects.filter(id=foreign.id).exists())
        self.assertFalse(NonWorkingDate.objects.filter(id=own.id).exists())

    def test_specialist_detail_exposes_upcoming_dates(self):
        specialist = User.objects.create_user(
            username="days_off_specialist", password="pass", role=ROLE_SPECIALIST,
        )
        NonWorkingDate.objects.create(user=specialist, date=self.day(-1))
        NonWorkingDate.objects.create(user=specialist, date=self.day(7))

        response = self.client.get(reverse("specialist-detail", args=[specialist.id]))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            [item["date"] for item in response.data["non_working_dates"]],
            [self.day(7).isoformat()],
        )


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


APNS_TOKEN = "a1b2c3d4" * 8
FCM_TOKEN = "dw34677Az09nhcHaj6BA05:APA91bG2HtL49IPyTDZF0Ixkbq"


class PushStatusApiTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="push_user", password="pass")
        self.client.force_authenticate(user=self.user)
        self.now = timezone.now()

    def _device(self, token, active=True, success_at=None, failure_at=None, error_code=""):
        device = GCMDevice.objects.create(user=self.user, registration_id=token, active=active)
        if success_at or failure_at:
            PushDeviceStatus.objects.create(
                device=device,
                last_success_at=success_at,
                last_failure_at=failure_at,
                last_error_code=error_code,
            )
        return device

    def _status(self):
        response = self.client.get(reverse("push-status"))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        return response.data

    def test_dead_device_failure_does_not_hide_working_device(self):
        self._device("working", success_at=self.now - timedelta(hours=1))
        self._device("dead", active=False, failure_at=self.now, error_code="INVALID_ARGUMENT")

        data = self._status()

        self.assertEqual(data["reason"], "ok")
        self.assertTrue(data["push_enabled"])
        # Код старой ошибки остаётся справочным полем.
        self.assertEqual(data["last_error_code"], "INVALID_ARGUMENT")

    def test_fresh_devices_after_old_failure_are_not_an_error(self):
        # Как у специалиста 65: давняя ошибка на погашенном токене и свежие
        # токены, на которые ещё ничего не отправляли.
        self._device("old", active=False, failure_at=self.now - timedelta(days=40),
                     error_code="INVALID_ARGUMENT")
        self._device("fresh-1")
        self._device("fresh-2")

        data = self._status()

        self.assertEqual(data["reason"], "unknown")
        self.assertEqual(data["active_devices"], 2)
        self.assertEqual(data["total_devices"], 3)

    def test_failure_on_one_active_device_does_not_hide_success_on_another(self):
        self._device("phone", success_at=self.now - timedelta(hours=1))
        self._device("tablet", failure_at=self.now, error_code="UNAVAILABLE")

        self.assertEqual(self._status()["reason"], "ok")

    def test_provider_error_when_every_active_device_failed(self):
        self._device("phone", success_at=self.now - timedelta(days=1),
                     failure_at=self.now, error_code="UNAVAILABLE")

        data = self._status()

        self.assertEqual(data["reason"], "provider_error")
        self.assertEqual(data["action"], "retry_later")

    def test_token_invalid_when_no_active_devices(self):
        self._device("dead", active=False, failure_at=self.now, error_code="UNREGISTERED")

        self.assertEqual(self._status()["reason"], "token_invalid")

    def test_no_devices(self):
        self.assertEqual(self._status()["reason"], "no_devices")


class PushDeviceRegistrationTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="push_owner", password="pass")
        self.other_user = User.objects.create_user(username="push_prev", password="pass")
        self.client.force_authenticate(user=self.user)

    def test_register_fcm_ignores_apns_token(self):
        response = self.client.post(
            reverse("register-fcm"), data={"registrationId": APNS_TOKEN}, format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(GCMDevice.objects.filter(registration_id=APNS_TOKEN).exists())

    def test_register_fcm_moves_token_to_current_user(self):
        GCMDevice.objects.create(user=self.other_user, registration_id=FCM_TOKEN, active=False)

        response = self.client.post(
            reverse("register-fcm"), data={"registrationId": FCM_TOKEN}, format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        device = GCMDevice.objects.get(registration_id=FCM_TOKEN)
        self.assertEqual(device.user, self.user)
        self.assertTrue(device.active)

    def test_device_gcm_ignores_apns_token(self):
        response = self.client.post(
            reverse("gcmdevice-list"), data={"registrationId": APNS_TOKEN}, format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(GCMDevice.objects.filter(registration_id=APNS_TOKEN).exists())

    def test_device_gcm_moves_token_to_current_user(self):
        GCMDevice.objects.create(user=self.other_user, registration_id=FCM_TOKEN)

        response = self.client.post(
            reverse("gcmdevice-list"), data={"registrationId": FCM_TOKEN}, format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(GCMDevice.objects.filter(registration_id=FCM_TOKEN).count(), 1)
        self.assertEqual(GCMDevice.objects.get(registration_id=FCM_TOKEN).user, self.user)

    def test_migration_deactivates_saved_apns_tokens(self):
        apns_device = GCMDevice.objects.create(user=self.user, registration_id=APNS_TOKEN)
        fcm_device = GCMDevice.objects.create(user=self.user, registration_id=FCM_TOKEN)
        migration = importlib.import_module("account.migrations.0057_deactivate_apns_tokens")

        migration.deactivate_apns_tokens(django_apps, None)

        apns_device.refresh_from_db()
        fcm_device.refresh_from_db()
        self.assertFalse(apns_device.active)
        self.assertTrue(fcm_device.active)


class PushDeviceDuplicatesTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="dup_owner", password="pass")
        self.client.force_authenticate(user=self.user)

    def _duplicates(self):
        GCMDevice.objects.create(user=self.user, registration_id=FCM_TOKEN)
        GCMDevice.objects.create(user=self.user, registration_id=FCM_TOKEN)

    def test_register_fcm_survives_duplicate_rows(self):
        # На проде здесь был 500: update_or_create → MultipleObjectsReturned.
        self._duplicates()

        response = self.client.post(
            reverse("register-fcm"), data={"registrationId": FCM_TOKEN}, format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(GCMDevice.objects.filter(registration_id=FCM_TOKEN).count(), 1)

    def test_device_gcm_drops_duplicate_rows(self):
        self._duplicates()

        response = self.client.post(
            reverse("gcmdevice-list"), data={"registrationId": FCM_TOKEN}, format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(GCMDevice.objects.filter(registration_id=FCM_TOKEN).count(), 1)

    def test_migration_keeps_newest_row_per_token(self):
        self._duplicates()
        newest = GCMDevice.objects.create(user=self.user, registration_id=FCM_TOKEN)
        single = GCMDevice.objects.create(user=self.user, registration_id="other-token")
        migration = importlib.import_module("account.migrations.0058_drop_duplicate_devices")

        migration.drop_duplicate_devices(django_apps, None)

        self.assertEqual(
            list(GCMDevice.objects.filter(registration_id=FCM_TOKEN).values_list("id", flat=True)),
            [newest.id],
        )
        self.assertTrue(GCMDevice.objects.filter(id=single.id).exists())


def _bishkek(year, month, day, hour, minute=0):
    return timezone.make_aware(datetime(year, month, day, hour, minute))


# 26.10.2026 — понедельник.
MONDAY = (2026, 10, 26)


class QuietHoursScheduleTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="quiet_specialist", password="pass", role=ROLE_SPECIALIST,
        )

    def _week(self, overrides=None):
        """Пн–Пт 9–18, сб и вс выходные; overrides — {день недели: поля}."""
        for day in range(1, 8):
            fields = {"from_time": time(9), "to_time": time(18), "is_day_off": day >= 6}
            fields.update((overrides or {}).get(day, {}))
            WorkSchedule.objects.create(user=self.user, day_of_week=day, **fields)

    def test_working_hours_are_not_quiet(self):
        self._week()
        self.assertIsNone(quiet_until(self.user, _bishkek(*MONDAY, 12)))

    def test_lunch_is_working_time(self):
        self._week({1: {"lunch_from_time": time(13), "lunch_to_time": time(14)}})
        self.assertIsNone(quiet_until(self.user, _bishkek(*MONDAY, 13, 30)))

    def test_evening_is_quiet_until_next_morning(self):
        self._week()
        self.assertEqual(quiet_until(self.user, _bishkek(*MONDAY, 20)), _bishkek(2026, 10, 27, 9))

    def test_weekend_is_quiet_until_monday(self):
        self._week()
        self.assertEqual(quiet_until(self.user, _bishkek(2026, 10, 30, 19)), _bishkek(2026, 11, 2, 9))

    def test_non_working_date_is_skipped(self):
        self._week()
        NonWorkingDate.objects.create(user=self.user, date=datetime(2026, 10, 27).date())
        self.assertEqual(quiet_until(self.user, _bishkek(*MONDAY, 20)), _bishkek(2026, 10, 28, 9))

    def test_overnight_shift_keeps_working_after_midnight(self):
        self._week({1: {"from_time": time(22), "to_time": time(6)}})
        self.assertIsNone(quiet_until(self.user, _bishkek(2026, 10, 27, 3)))

    def test_round_the_clock_day_starts_at_midnight(self):
        self._week({3: {"is_round_the_clock": True}})
        self.assertEqual(quiet_until(self.user, _bishkek(2026, 10, 27, 20)), _bishkek(2026, 10, 28, 0))

    def test_no_schedule_means_no_quiet(self):
        self.assertIsNone(quiet_until(self.user, _bishkek(*MONDAY, 23)))


@patch("account.services.quiet_hours.notify_user")
@patch("account.services.quiet_hours.chat_client")
class QuietHoursSyncTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="quiet_sync", password="pass", role=ROLE_SPECIALIST,
        )
        self.client_user = User.objects.create_user(username="quiet_client", password="pass")
        for day in range(1, 8):
            WorkSchedule.objects.create(
                user=self.user, day_of_week=day, from_time=time(9), to_time=time(18),
            )

    def _preferences(self, stream):
        return [call.kwargs["data"]["preferences"][0] for call in stream.post.call_args_list]

    def test_evening_pauses_chat_pushes_until_next_shift(self, stream, notify):
        sync_quiet_hours(self.user, _bishkek(*MONDAY, 20))
        sync_quiet_hours(self.user, _bishkek(*MONDAY, 20, 5))

        # Второй проход ничего не шлёт: конец тишины тот же.
        self.assertEqual(
            self._preferences(stream),
            [{"user_id": str(self.user.id), "chat_level": "all", "disabled_until": "2026-10-27T03:00:00Z"}],
        )
        self.assertEqual(QuietHoursState.objects.get(user=self.user).quiet_since, _bishkek(*MONDAY, 20))
        notify.assert_not_called()

    def test_shift_start_resumes_pushes_and_sends_summary(self, stream, notify):
        stream.unread_counts.return_value = {
            "total_unread_count": 5,
            "channels": [{"unread_count": 3}, {"unread_count": 2}, {"unread_count": 0}],
        }
        sync_quiet_hours(self.user, _bishkek(*MONDAY, 20))
        tariff = Tariff.objects.create(name="Платный", price=100, specialist=self.user)
        AccessOrder.objects.create(
            tariff=tariff, client=self.client_user, specialist=self.user,
            payment_status="success", activated_at=_bishkek(*MONDAY, 23),
        )

        sync_quiet_hours(self.user, _bishkek(2026, 10, 27, 9, 2))

        self.assertEqual(self._preferences(stream)[-1], {"user_id": str(self.user.id), "remove_disable": True})
        notify.assert_called_once()
        self.assertEqual(notify.call_args.kwargs["title"], "Пока вас не было")
        self.assertEqual(
            notify.call_args.kwargs["message"],
            "Оформлено тарифов: 1. Непрочитанных сообщений: 5 от 2 клиентов.",
        )
        self.assertEqual(notify.call_args.kwargs["notification_type"], Notification.TYPE_QUIET_HOURS_SUMMARY)
        self.assertFalse(QuietHoursState.objects.filter(user=self.user).exists())

    def test_nothing_missed_means_no_summary(self, stream, notify):
        stream.unread_counts.return_value = {"total_unread_count": 0, "channels": []}
        sync_quiet_hours(self.user, _bishkek(*MONDAY, 20))

        sync_quiet_hours(self.user, _bishkek(2026, 10, 27, 9, 2))

        notify.assert_not_called()
        self.assertFalse(QuietHoursState.objects.filter(user=self.user).exists())

    def test_notify_always_ends_quiet_without_summary(self, stream, notify):
        sync_quiet_hours(self.user, _bishkek(*MONDAY, 20))
        self.user.notify_outside_work_hours = True
        self.user.save(update_fields=["notify_outside_work_hours"])

        sync_quiet_hours(self.user, _bishkek(*MONDAY, 21))

        self.assertEqual(self._preferences(stream)[-1], {"user_id": str(self.user.id), "remove_disable": True})
        notify.assert_not_called()
        self.assertFalse(QuietHoursState.objects.filter(user=self.user).exists())

    def test_clients_are_never_quiet(self, stream, notify):
        client = User.objects.create_user(username="quiet_plain_client", password="pass")

        sync_quiet_hours(client, _bishkek(*MONDAY, 23))

        stream.post.assert_not_called()


class QuietHoursSummaryTextTests(APITestCase):
    def test_texts(self):
        self.assertIsNone(summary_text(0, 0, 0))
        self.assertEqual(summary_text(0, 1, 1), "Непрочитанных сообщений: 1 от 1 клиента.")
        self.assertEqual(summary_text(0, 30, 21), "Непрочитанных сообщений: 30 от 21 клиента.")
        self.assertEqual(summary_text(0, 12, 11), "Непрочитанных сообщений: 12 от 11 клиентов.")
        self.assertEqual(summary_text(2, 0, 0), "Оформлено тарифов: 2.")


class NotifyOutsideWorkHoursApiTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="quiet_api", password="pass", role=ROLE_SPECIALIST,
        )
        self.client.force_authenticate(user=self.user)

    @patch("account.views.user.sync_quiet_hours")
    def test_patch_saves_setting_and_syncs_right_away(self, sync):
        response = self.client.patch(
            reverse("update-notify-outside-work-hours"),
            data={"notifyOutsideWorkHours": True},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.user.refresh_from_db()
        self.assertTrue(self.user.notify_outside_work_hours)
        sync.assert_called_once_with(self.user)

    def test_profile_exposes_setting(self):
        response = self.client.get(reverse("user-me"))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIs(response.data["notify_outside_work_hours"], False)
