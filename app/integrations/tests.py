from datetime import timedelta
from urllib.parse import parse_qs, urlparse
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from account.models import ROLE_CLIENT
from integrations.models import SSOLoginToken

User = get_user_model()


@override_settings(
    MEDCRM_SSO_WEB_URL="https://medcrm.example",
    MEDCRM_SSO_INTEGRATION_SECRET="test-secret",
    MEDCRM_SSO_TTL_SECONDS=120,
)
class MedCRMSSOTests(APITestCase):
    def setUp(self):
        self.chat_client_patcher = patch("account.models.user.chat_client")
        self.chat_client_patcher.start()
        self.addCleanup(self.chat_client_patcher.stop)

        self.user = User.objects.create_user(
            username="sso_user",
            phone_number="+996555111222",
            first_name="A",
            last_name="B",
            role=ROLE_CLIENT,
            password="pass",
        )

    def test_webview_url_requires_authentication(self):
        response = self.client.post(reverse("medcrm-sso-webview-url"), {})
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_webview_url_returns_raw_token_but_stores_only_hash(self):
        self.client.force_authenticate(user=self.user)

        response = self.client.post(
            reverse("medcrm-sso-webview-url"),
            {"next": "/dashboard"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        url = response.data["url"]
        parsed_url = urlparse(url)
        token = parse_qs(parsed_url.query)["token"][0]
        next_path = parse_qs(parsed_url.query)["next"][0]
        sso_token = SSOLoginToken.objects.get()

        self.assertEqual(f"{parsed_url.scheme}://{parsed_url.netloc}{parsed_url.path}", "https://medcrm.example/sso")
        self.assertEqual(next_path, "/dashboard")
        self.assertNotEqual(sso_token.token_hash, token)
        self.assertEqual(sso_token.token_hash, SSOLoginToken.hash_token(token))
        self.assertEqual(sso_token.next_path, "/dashboard")

    def test_webview_url_rejects_next_without_leading_slash(self):
        self.client.force_authenticate(user=self.user)

        response = self.client.post(
            reverse("medcrm-sso-webview-url"),
            {"next": "login"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("next", response.data)

    def test_verify_rejects_invalid_secret(self):
        raw_token = SSOLoginToken.create_for_user(self.user)

        response = self.client.post(
            reverse("medcrm-sso-verify-token"),
            {"token": raw_token},
            HTTP_X_INTEGRATION_SECRET="wrong",
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_verify_rejects_missing_token(self):
        response = self.client.post(
            reverse("medcrm-sso-verify-token"),
            {},
            HTTP_X_INTEGRATION_SECRET="test-secret",
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_verify_rejects_expired_token(self):
        raw_token = SSOLoginToken.create_for_user(self.user)
        SSOLoginToken.objects.update(expires_at=timezone.now() - timedelta(seconds=1))

        response = self.client.post(
            reverse("medcrm-sso-verify-token"),
            {"token": raw_token},
            HTTP_X_INTEGRATION_SECRET="test-secret",
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(response.data, {"valid": False})

    def test_verify_returns_user_and_marks_token_used_once(self):
        raw_token = SSOLoginToken.create_for_user(self.user, next_path="/dashboard")

        first_response = self.client.post(
            reverse("medcrm-sso-verify-token"),
            {"token": raw_token},
            HTTP_X_INTEGRATION_SECRET="test-secret",
            format="json",
        )
        second_response = self.client.post(
            reverse("medcrm-sso-verify-token"),
            {"token": raw_token},
            HTTP_X_INTEGRATION_SECRET="test-secret",
            format="json",
        )

        self.assertEqual(first_response.status_code, status.HTTP_200_OK)
        self.assertEqual(first_response.data["valid"], True)
        self.assertEqual(first_response.data["user"]["id"], str(self.user.id))
        self.assertEqual(first_response.data["user"]["phone"], "+996555111222")
        self.assertEqual(first_response.data["user"]["role"], ROLE_CLIENT)
        self.assertEqual(first_response.data["next"], "/dashboard")
        self.assertIsNotNone(SSOLoginToken.objects.get().used_at)

        self.assertEqual(second_response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(second_response.data, {"valid": False})
