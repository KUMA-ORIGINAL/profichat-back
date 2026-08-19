import logging

from django.conf import settings
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from integrations.telegram_admin import handle_admin_update

logger = logging.getLogger(__name__)

MESSAGE_INVALID_WEBHOOK_SECRET = "Invalid webhook secret."


def admin_webhook_secret():
    return getattr(settings, "TELEGRAM_ADMIN_WEBHOOK_SECRET", "") or getattr(
        settings, "TELEGRAM_AUTH_WEBHOOK_SECRET", ""
    )


def check_webhook_secret_token(request) -> bool:
    """Проверяет заголовок Telegram, если secret_token задан при setWebhook."""
    expected = getattr(settings, "TELEGRAM_WEBHOOK_SECRET_TOKEN", "")
    if not expected:
        return True
    return request.headers.get("X-Telegram-Bot-Api-Secret-Token") == expected


@extend_schema(exclude=True)
class TelegramAdminWebhookView(APIView):
    """Webhook бота уведомлений: кнопки «Одобрить» / «Отклонить» под заявкой."""

    authentication_classes = []
    permission_classes = [AllowAny]

    def post(self, request, webhook_secret=None):
        expected_secret = admin_webhook_secret()
        if expected_secret and webhook_secret != expected_secret:
            return Response({"detail": MESSAGE_INVALID_WEBHOOK_SECRET}, status=status.HTTP_403_FORBIDDEN)

        if not check_webhook_secret_token(request):
            return Response({"detail": MESSAGE_INVALID_WEBHOOK_SECRET}, status=status.HTTP_403_FORBIDDEN)

        try:
            handle_admin_update(request.data if isinstance(request.data, dict) else {})
        except Exception:
            # Telegram ретраит апдейт на не-200 — логируем и подтверждаем приём.
            logger.exception("Failed to handle Telegram admin update")

        return Response({"ok": True}, status=status.HTTP_200_OK)
