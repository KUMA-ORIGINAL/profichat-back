import secrets
from urllib.parse import urlencode

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from integrations.models import SSOLoginToken
from integrations.serializers import (
    SecondSystemWebviewUrlRequestSerializer,
    SecondSystemWebviewUrlResponseSerializer,
    VerifySecondSystemSSOTokenRequestSerializer,
    VerifySecondSystemSSOTokenResponseSerializer,
)


def _get_medcrm_web_url():
    return (
        getattr(settings, "MEDCRM_SSO_WEB_URL", "")
        or getattr(settings, "SECOND_SYSTEM_WEB_URL", "")
        or ""
    ).rstrip("/")


def _get_medcrm_integration_secret():
    return (
        getattr(settings, "MEDCRM_SSO_INTEGRATION_SECRET", "")
        or getattr(settings, "SECOND_SYSTEM_INTEGRATION_SECRET", "")
        or ""
    )


class SecondSystemWebviewUrlView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["MedCRM SSO"],
        summary="Create MedCRM WebView SSO URL",
        request=SecondSystemWebviewUrlRequestSerializer,
        responses={200: SecondSystemWebviewUrlResponseSerializer},
    )
    def post(self, request):
        serializer = SecondSystemWebviewUrlRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        web_url = _get_medcrm_web_url()
        if not web_url:
            return Response(
                {"detail": "MEDCRM_SSO_WEB_URL is not configured."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        if not request.user.phone_number:
            return Response(
                {"detail": "Current user has no phone_number."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        next_path = serializer.validated_data.get("next", "/")
        raw_token = SSOLoginToken.create_for_user(request.user, next_path=next_path)
        query = urlencode({"token": raw_token, "next": next_path})
        return Response({"url": f"{web_url}/sso?{query}"})


class VerifySecondSystemSSOTokenView(APIView):
    authentication_classes = []
    permission_classes = []

    @extend_schema(
        tags=["MedCRM SSO"],
        summary="Verify MedCRM SSO token",
        request=VerifySecondSystemSSOTokenRequestSerializer,
        responses={200: VerifySecondSystemSSOTokenResponseSerializer},
    )
    def post(self, request):
        expected_secret = _get_medcrm_integration_secret()
        provided_secret = request.headers.get("X-Integration-Secret", "")

        if not expected_secret or not secrets.compare_digest(provided_secret, expected_secret):
            return Response(
                {"detail": "Invalid integration secret"},
                status=status.HTTP_403_FORBIDDEN,
            )

        serializer = VerifySecondSystemSSOTokenRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        raw_token = serializer.validated_data["token"]
        token_hash = SSOLoginToken.hash_token(raw_token)

        with transaction.atomic():
            sso_token = (
                SSOLoginToken.objects.select_for_update()
                .select_related("user")
                .filter(
                    token_hash=token_hash,
                    partner=SSOLoginToken.PARTNER_MEDCRM,
                )
                .first()
            )

            if not sso_token or not sso_token.is_valid:
                return Response({"valid": False}, status=status.HTTP_401_UNAUTHORIZED)

            user = sso_token.user
            if not user.phone_number:
                return Response({"valid": False}, status=status.HTTP_401_UNAUTHORIZED)

            sso_token.used_at = timezone.now()
            sso_token.save(update_fields=["used_at"])

        return Response(
            {
                "valid": True,
                "user": {
                    "id": str(user.id),
                    "phone": str(user.phone_number),
                    "role": user.role or "",
                    "first_name": user.first_name or "",
                    "last_name": user.last_name or "",
                },
                "next": sso_token.next_path,
            }
        )
