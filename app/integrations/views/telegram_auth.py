import logging
import secrets
from datetime import datetime, timezone as dt_timezone

import requests
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.cache import cache
from drf_spectacular.utils import OpenApiExample, OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.token_blacklist.models import BlacklistedToken, OutstandingToken
from rest_framework_simplejwt.tokens import RefreshToken

from account.services.user import generate_unique_username
from common.stream_client import chat_client
from integrations.serializers import (
    TelegramAuthErrorResponseSerializer,
    TelegramAuthStartResponseSerializer,
    TelegramAuthStatusRequestSerializer,
    TelegramAuthStatusResponseSerializer,
)
from integrations.telegram_auth.constants import (
    CHAT_CACHE_KEY_PREFIX,
    CONSUMED_SESSION_TTL_SECONDS,
    DEFAULT_SESSION_TTL_SECONDS,
    MESSAGE_AUTH_CONFIRMED,
    MESSAGE_CONTACT_REQUEST,
    MESSAGE_EXPIRED_SESSION,
    MESSAGE_INACTIVE_SESSION,
    MESSAGE_INVALID_WEBHOOK_SECRET,
    MESSAGE_NOT_OWN_CONTACT,
    MESSAGE_SESSION_ALREADY_USED,
    MESSAGE_SESSION_NOT_FOUND,
    SESSION_CACHE_KEY_PREFIX,
    SESSION_ID_TOKEN_BYTES,
    STATUS_COMPLETED,
    STATUS_PENDING,
    STATUS_WAITING_CONTACT,
    TELEGRAM_CONTACT_BUTTON_TEXT,
    TELEGRAM_SEND_TIMEOUT_SECONDS,
)

logger = logging.getLogger(__name__)
User = get_user_model()


def _telegram_auth_session_ttl_seconds():
    return int(getattr(settings, "TELEGRAM_AUTH_SESSION_TTL_SECONDS", DEFAULT_SESSION_TTL_SECONDS))


def _session_cache_key(session_id):
    return f"{SESSION_CACHE_KEY_PREFIX}:{session_id}"


def _chat_cache_key(chat_id):
    return f"{CHAT_CACHE_KEY_PREFIX}:{chat_id}"


def _build_bot_link(session_id):
    bot_username = getattr(settings, "TELEGRAM_AUTH_BOT_USERNAME", "")
    if not bot_username:
        return ""
    return f"https://t.me/{bot_username}?start={session_id}"


def _blacklist_user_tokens(user):
    tokens = OutstandingToken.objects.filter(user=user)
    for token in tokens:
        try:
            BlacklistedToken.objects.get_or_create(token=token)
        except Exception:
            logger.exception("Failed to blacklist token for user=%s", user.id)


def _issue_auth_payload_for_user(user):
    _blacklist_user_tokens(user)
    refresh = RefreshToken.for_user(user)
    stream_token = chat_client.create_token(str(user.id))
    return {
        "status": STATUS_COMPLETED,
        "user_id": user.id,
        "refresh": str(refresh),
        "access": str(refresh.access_token),
        "stream_token": stream_token,
    }


@extend_schema(
    tags=["Telegram Auth"],
    request=None,
    description=(
        "Создает сессию входа через Telegram.\n\n"
        "Статусы:\n"
        f"- {STATUS_PENDING}: сессия создана, ожидается переход пользователя в бота.\n"
        f"- {STATUS_WAITING_CONTACT}: пользователь открыл бота, ожидается отправка контакта.\n"
        f"- {STATUS_COMPLETED}: контакт подтвержден, можно забирать токены через status endpoint."
    ),
    responses={200: OpenApiResponse(response=TelegramAuthStartResponseSerializer)},
    examples=[
        OpenApiExample(
            "Start response",
            value={
                "session_id": "abc123",
                "status": STATUS_PENDING,
                "bot_link": "https://t.me/your_bot?start=abc123",
                "expires_in": 300,
            },
            response_only=True,
            status_codes=["200"],
        ),
    ],
)
class TelegramAuthStartView(APIView):
    """Старт сессии для входа в приложение через Telegram."""

    authentication_classes = []
    permission_classes = [AllowAny]

    def post(self, request):
        session_id = secrets.token_urlsafe(SESSION_ID_TOKEN_BYTES)
        ttl_seconds = _telegram_auth_session_ttl_seconds()
        now_iso = datetime.now(dt_timezone.utc).isoformat()

        cache.set(
            _session_cache_key(session_id),
            {
                "status": STATUS_PENDING,
                "created_at": now_iso,
            },
            timeout=ttl_seconds,
        )

        return Response(
            {
                "session_id": session_id,
                "status": STATUS_PENDING,
                "bot_link": _build_bot_link(session_id),
                "expires_in": ttl_seconds,
            },
            status=status.HTTP_200_OK,
        )


@extend_schema(
    tags=["Telegram Auth"],
    request=TelegramAuthStatusRequestSerializer,
    description=(
        "Возвращает текущий статус сессии Telegram auth.\n\n"
        "Возвращаемые статусы:\n"
        f"- {STATUS_PENDING}: сессия еще не активирована в боте.\n"
        f"- {STATUS_WAITING_CONTACT}: пользователь перешел в бота, но контакт еще не отправлен.\n"
        f"- {STATUS_COMPLETED}: контакт принят, в ответе будут access/refresh/stream_token.\n\n"
        "Коды ошибок:\n"
        "- 404: сессия не найдена или истекла.\n"
        "- 410: токены уже были выданы ранее для этой сессии."
    ),
    responses={
        200: OpenApiResponse(
            response=TelegramAuthStatusResponseSerializer,
            examples=[
                OpenApiExample(
                    "Status completed with tokens",
                    value={
                        "status": STATUS_COMPLETED,
                        "refresh": "eyJ0eXAiOiJKV1QiLCJh...",
                        "access": "eyJ0eXAiOiJKV1QiLCJh...",
                        "stream_token": "stream-token-value",
                    },
                    response_only=True,
                ),
                OpenApiExample(
                    "Status pending",
                    value={"status": STATUS_PENDING},
                    response_only=True,
                ),
                OpenApiExample(
                    "Status waiting_contact",
                    value={"status": STATUS_WAITING_CONTACT},
                    response_only=True,
                ),
            ],
        ),
        404: OpenApiResponse(
            response=TelegramAuthErrorResponseSerializer,
            examples=[
                OpenApiExample(
                    "Session expired",
                    value={"detail": MESSAGE_SESSION_NOT_FOUND},
                    response_only=True,
                ),
            ],
        ),
        410: OpenApiResponse(
            response=TelegramAuthErrorResponseSerializer,
            examples=[
                OpenApiExample(
                    "Session consumed",
                    value={"detail": MESSAGE_SESSION_ALREADY_USED},
                    response_only=True,
                ),
            ],
        ),
    },
)
class TelegramAuthStatusView(APIView):
    """Проверка статуса сессии входа через Telegram."""

    authentication_classes = []
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = TelegramAuthStatusRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        session_id = serializer.validated_data["session_id"]
        key = _session_cache_key(session_id)
        session = cache.get(key)
        if not session:
            return Response(
                {"detail": MESSAGE_SESSION_NOT_FOUND},
                status=status.HTTP_404_NOT_FOUND,
            )

        session_status = session.get("status", STATUS_PENDING)
        if session_status != STATUS_COMPLETED:
            return Response({"status": session_status}, status=status.HTTP_200_OK)

        if session.get("consumed"):
            return Response(
                {"detail": MESSAGE_SESSION_ALREADY_USED},
                status=status.HTTP_410_GONE,
            )

        session["consumed"] = True
        cache.set(key, session, timeout=CONSUMED_SESSION_TTL_SECONDS)

        return Response(
            {
                "status": STATUS_COMPLETED,
                "refresh": session.get("refresh"),
                "access": session.get("access"),
                "stream_token": session.get("stream_token"),
            },
            status=status.HTTP_200_OK,
        )


class TelegramAuthWebhookView(APIView):
    """Webhook для Telegram-бота авторизации."""

    authentication_classes = []
    permission_classes = [AllowAny]

    def post(self, request, webhook_secret=None):
        expected_secret = getattr(settings, "TELEGRAM_AUTH_WEBHOOK_SECRET", "")
        if expected_secret and webhook_secret != expected_secret:
            return Response({"detail": MESSAGE_INVALID_WEBHOOK_SECRET}, status=status.HTTP_403_FORBIDDEN)

        message = (
            request.data.get("message")
            or request.data.get("edited_message")
            or {}
        )
        chat_id = (message.get("chat") or {}).get("id")
        if not chat_id:
            return Response({"ok": True}, status=status.HTTP_200_OK)

        contact = message.get("contact")
        if contact:
            self._handle_contact_message(message=message, chat_id=chat_id)
            return Response({"ok": True}, status=status.HTTP_200_OK)

        text = (message.get("text") or "").strip()
        if text.startswith("/start"):
            session_id = self._extract_session_id_from_start(text)
            if not session_id:
                self._send_contact_request(chat_id)
                return Response({"ok": True}, status=status.HTTP_200_OK)

            session = cache.get(_session_cache_key(session_id))
            if not session:
                self._telegram_send_message(
                    chat_id=chat_id,
                    text=MESSAGE_EXPIRED_SESSION,
                )
                return Response({"ok": True}, status=status.HTTP_200_OK)

            ttl_seconds = _telegram_auth_session_ttl_seconds()
            cache.set(_chat_cache_key(chat_id), session_id, timeout=ttl_seconds)
            session["status"] = STATUS_WAITING_CONTACT
            cache.set(_session_cache_key(session_id), session, timeout=ttl_seconds)
            self._send_contact_request(chat_id)

        return Response({"ok": True}, status=status.HTTP_200_OK)

    def _send_contact_request(self, chat_id):
        reply_markup = {
            "keyboard": [[{"text": TELEGRAM_CONTACT_BUTTON_TEXT, "request_contact": True}]],
            "resize_keyboard": True,
            "one_time_keyboard": True,
        }
        self._telegram_send_message(
            chat_id=chat_id,
            text=MESSAGE_CONTACT_REQUEST,
            reply_markup=reply_markup,
        )

    def _handle_contact_message(self, message, chat_id):
        from_user = message.get("from") or {}
        contact = message.get("contact") or {}
        from_user_id = from_user.get("id")
        contact_user_id = contact.get("user_id")

        if from_user_id and contact_user_id and from_user_id != contact_user_id:
            self._send_contact_request(chat_id)
            self._telegram_send_message(
                chat_id=chat_id,
                text=MESSAGE_NOT_OWN_CONTACT,
            )
            return

        phone_number = self._normalize_phone(contact.get("phone_number"))
        if not phone_number:
            self._send_contact_request(chat_id)
            return

        session_id = cache.get(_chat_cache_key(chat_id))
        if not session_id:
            self._telegram_send_message(
                chat_id=chat_id,
                text=MESSAGE_INACTIVE_SESSION,
            )
            return

        user = User.objects.filter(phone_number=phone_number).order_by("-is_active", "-id").first()
        created = False
        if user is None:
            user = User.objects.create(
                phone_number=phone_number,
                username=generate_unique_username(),
                is_active=True,
            )
            created = True
            try:
                from common.telegram_notifier import notify_new_client_registration
                notify_new_client_registration(user)
            except Exception:
                logger.exception("Failed to send Telegram notification for new user %s", user.id)
        logger.info("Telegram auth contact received: user_id=%s created=%s", user.id, created)
        ttl_seconds = _telegram_auth_session_ttl_seconds()
        auth_payload = _issue_auth_payload_for_user(user)
        cache.set(_session_cache_key(session_id), auth_payload, timeout=ttl_seconds)
        cache.delete(_chat_cache_key(chat_id))
        self._telegram_send_message(
            chat_id=chat_id,
            text=MESSAGE_AUTH_CONFIRMED,
            reply_markup={"remove_keyboard": True},
        )

    @staticmethod
    def _normalize_phone(phone_number):
        if not phone_number:
            return None
        normalized = str(phone_number).strip().replace(" ", "")
        if not normalized.startswith("+"):
            normalized = f"+{normalized}"
        return normalized

    @staticmethod
    def _extract_session_id_from_start(text):
        # Формат deep link: /start <payload>
        parts = text.split(maxsplit=1)
        if len(parts) < 2:
            return None
        return parts[1].strip()

    @staticmethod
    def _telegram_send_message(chat_id, text, reply_markup=None):
        bot_token = getattr(settings, "TELEGRAM_AUTH_BOT_TOKEN", "") or getattr(settings, "TELEGRAM_BOT_TOKEN", "")
        if not bot_token:
            logger.warning("Telegram auth bot token is not configured.")
            return False

        payload = {
            "chat_id": chat_id,
            "text": text,
        }
        if reply_markup is not None:
            payload["reply_markup"] = reply_markup

        try:
            response = requests.post(
                f"https://api.telegram.org/bot{bot_token}/sendMessage",
                json=payload,
                timeout=TELEGRAM_SEND_TIMEOUT_SECONDS,
            )
            response.raise_for_status()
        except requests.RequestException:
            logger.exception("Failed to send Telegram auth message")
            return False
        return True
