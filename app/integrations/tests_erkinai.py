"""Справочник ErkinAI: зеркало организаций и привязка специалиста."""

from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from account.models import Organization, OrganizationAddress
from account.models.user import ROLE_CLIENT, ROLE_SPECIALIST
from integrations.erkinai import client, staff
from integrations.erkinai.organization_sync import sync_organizations
from integrations.models import ErkinAISyncState

User = get_user_model()

PHONE = "+996700111222"


def org_payload(**overrides):
    payload = {
        "id": 1,
        "slug": "pediatr",
        "name": "Педиатр",
        "status": "active",
        "isActive": True,
        "branches": [],
    }
    payload.update(overrides)
    return payload


def branch_payload(**overrides):
    payload = {"id": 10, "name": "Центральный", "address": "Бишкек, ул. Панфилова 1"}
    payload.update(overrides)
    return payload


def card_payload(**overrides):
    payload = {
        "id": 42,
        "fullName": "Осмонова Айгуль Кубанычбековна",
        "phone": PHONE,
        "email": "doc@example.com",
        "bio": "О враче",
        "education": "КГМА",
        "experienceYears": 7,
        "gender": "female",
        "hasCrmAccount": False,
        "organization": {"id": 1, "slug": "pediatr", "name": "Педиатр"},
        "branch": None,
    }
    payload.update(overrides)
    return payload


def fake_feed(organizations, synced_at="2026-08-30T12:00:00+00:00"):
    return patch.object(
        client, "fetch_organizations", return_value=(organizations, synced_at)
    )


class OrganizationSyncTests(TestCase):

    def test_creates_organization_with_erkinai_id(self):
        with fake_feed([org_payload()]):
            result = sync_organizations()

        organization = Organization.objects.get(erkinai_id=1)
        self.assertEqual(organization.name, "Педиатр")
        self.assertTrue(organization.is_active)
        self.assertEqual(result.created, 1)

    def test_second_run_updates_instead_of_duplicating(self):
        with fake_feed([org_payload()]):
            sync_organizations()
        with fake_feed([org_payload(name="Педиатр Плюс")]):
            result = sync_organizations()

        self.assertEqual(Organization.objects.filter(erkinai_id=1).count(), 1)
        self.assertEqual(Organization.objects.get(erkinai_id=1).name, "Педиатр Плюс")
        self.assertEqual(result.updated, 1)

    def test_archived_organization_is_switched_off_not_deleted(self):
        """На неё ссылаются профили специалистов — удаление порвало бы их."""
        with fake_feed([org_payload()]):
            sync_organizations()
        with fake_feed([org_payload(status="archived", isActive=False)]):
            result = sync_organizations()

        organization = Organization.objects.get(erkinai_id=1)
        self.assertFalse(organization.is_active)
        self.assertEqual(result.deactivated, 1)

    def test_manually_created_organization_is_left_alone(self):
        own = Organization.objects.create(name="Свой салон")

        with fake_feed([org_payload()]):
            sync_organizations()

        own.refresh_from_db()
        self.assertIsNone(own.erkinai_id)
        self.assertTrue(own.is_active)

    def test_name_clash_gets_a_suffix_instead_of_crashing(self):
        Organization.objects.create(name="Педиатр")

        with fake_feed([org_payload()]):
            sync_organizations()

        self.assertEqual(
            Organization.objects.get(erkinai_id=1).name, "Педиатр (ErkinAI #1)"
        )

    def test_branches_become_addresses(self):
        with fake_feed([org_payload(branches=[branch_payload()])]):
            sync_organizations()

        address = OrganizationAddress.objects.get(erkinai_branch_id=10)
        self.assertEqual(address.address, "Бишкек, ул. Панфилова 1")
        self.assertTrue(address.is_primary)

    def test_address_is_updated_not_duplicated(self):
        with fake_feed([org_payload(branches=[branch_payload()])]):
            sync_organizations()
        with fake_feed([org_payload(branches=[branch_payload(address="Новый адрес")])]):
            sync_organizations()

        self.assertEqual(OrganizationAddress.objects.count(), 1)
        self.assertEqual(
            OrganizationAddress.objects.get().address, "Новый адрес"
        )

    def test_vanished_branch_takes_its_address_away(self):
        with fake_feed([org_payload(branches=[branch_payload()])]):
            sync_organizations()
        with fake_feed([org_payload(branches=[])]):
            sync_organizations()

        self.assertEqual(OrganizationAddress.objects.count(), 0)

    def test_hand_made_address_survives_the_sync(self):
        """Синхронизация владеет только тем, что сама и привезла."""
        with fake_feed([org_payload()]):
            sync_organizations()
        organization = Organization.objects.get(erkinai_id=1)
        OrganizationAddress.objects.create(organization=organization, address="Своё")

        with fake_feed([org_payload(branches=[branch_payload()])]):
            sync_organizations()

        self.assertTrue(
            OrganizationAddress.objects.filter(address="Своё").exists()
        )

    def test_sync_state_advances_and_narrows_the_next_run(self):
        with fake_feed([org_payload()]):
            sync_organizations()

        state = ErkinAISyncState.objects.get(feed=ErkinAISyncState.FEED_ORGANIZATIONS)
        self.assertIsNotNone(state.synced_at)

        with patch.object(
            client, "fetch_organizations", return_value=([], None)
        ) as fetch:
            sync_organizations()

        self.assertIsNotNone(fetch.call_args.kwargs["updated_since"])

    def test_full_run_ignores_the_window(self):
        with fake_feed([org_payload()]):
            sync_organizations()

        with patch.object(
            client, "fetch_organizations", return_value=([], None)
        ) as fetch:
            sync_organizations(full=True)

        self.assertIsNone(fetch.call_args.kwargs["updated_since"])

    def test_row_without_id_is_skipped_not_fatal(self):
        with fake_feed([org_payload(id=None), org_payload(id=2, name="Вторая")]):
            result = sync_organizations()

        self.assertEqual(result.skipped, 1)
        self.assertEqual(result.created, 1)


class BecomeSpecialistTests(TestCase):

    def setUp(self):
        self.user = User.objects.create(username="u1", phone_number=PHONE)

    def test_apply_card_makes_a_specialist_and_links_the_clinic(self):
        staff.apply_card(self.user, card_payload())

        self.user.refresh_from_db()
        self.assertEqual(self.user.role, ROLE_SPECIALIST)
        self.assertEqual(self.user.last_name, "Осмонова")
        self.assertEqual(self.user.first_name, "Айгуль")
        self.assertEqual(self.user.middle_name, "Кубанычбековна")
        self.assertEqual(self.user.education, "КГМА")
        self.assertEqual(self.user.work_experience, "7")
        self.assertEqual(self.user.organization.erkinai_id, 1)

    def test_existing_profile_data_is_not_overwritten(self):
        """Человек мог заполнить профиль до привязки — CRM его не затирает."""
        self.user.description = "Своё описание"
        self.user.save()

        staff.apply_card(self.user, card_payload())

        self.user.refresh_from_db()
        self.assertEqual(self.user.description, "Своё описание")

    def test_organization_is_reused_by_erkinai_id(self):
        existing = Organization.objects.create(name="Педиатр", erkinai_id=1)

        staff.apply_card(self.user, card_payload())

        self.user.refresh_from_db()
        self.assertEqual(self.user.organization_id, existing.id)
        self.assertEqual(Organization.objects.count(), 1)

    def test_same_named_organization_is_adopted_rather_than_duplicated(self):
        existing = Organization.objects.create(name="Педиатр")

        staff.apply_card(self.user, card_payload())

        existing.refresh_from_db()
        self.assertEqual(existing.erkinai_id, 1)
        self.assertEqual(Organization.objects.count(), 1)

    def test_find_card_refuses_a_card_that_is_not_yours(self):
        """Присланный клиентом id ничего не доказывает — ищем по его телефону."""
        with patch.object(staff, "offer_for_phone", return_value=[card_payload()]):
            self.assertIsNone(staff.find_card(PHONE, 999))
            self.assertIsNotNone(staff.find_card(PHONE, 42))

    def test_endpoint_rejects_a_foreign_employee_id(self):
        api = APIClient()
        api.force_authenticate(user=self.user)
        with patch.object(staff, "offer_for_phone", return_value=[card_payload()]):
            response = api.post(
                reverse("erkinai_become_specialist"),
                data={"employeeId": 999},
                format="json",
            )

        self.assertEqual(response.status_code, 404)
        self.user.refresh_from_db()
        self.assertEqual(self.user.role, ROLE_CLIENT)

    def test_endpoint_applies_own_card(self):
        api = APIClient()
        api.force_authenticate(user=self.user)
        with patch.object(staff, "offer_for_phone", return_value=[card_payload()]):
            response = api.post(
                reverse("erkinai_become_specialist"),
                data={"employeeId": 42},
                format="json",
            )

        self.assertEqual(response.status_code, 200)
        self.user.refresh_from_db()
        self.assertEqual(self.user.role, ROLE_SPECIALIST)


class OfferTests(TestCase):

    def test_unreachable_erkinai_never_breaks_registration(self):
        with patch.object(client, "is_configured", return_value=True), patch.object(
            client, "lookup_staff_by_phone", side_effect=client.ErkinAIError("no")
        ):
            self.assertEqual(staff.offer_for_phone(PHONE), [])

    def test_unconfigured_deployment_offers_nothing(self):
        with patch.object(client, "is_configured", return_value=False):
            self.assertEqual(staff.offer_for_phone(PHONE), [])

    def test_existing_specialist_is_not_offered_again(self):
        from account.views.auth import VerifyOTPView

        user = User.objects.create(
            username="u2", phone_number=PHONE, role=ROLE_SPECIALIST
        )
        self.assertEqual(VerifyOTPView.erkinai_offer(user), [])
