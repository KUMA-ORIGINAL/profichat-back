from rest_framework import serializers

from integrations.telegram_auth.constants import TELEGRAM_AUTH_STATUSES


class TelegramAuthStartResponseSerializer(serializers.Serializer):
    session_id = serializers.CharField(
        help_text="Идентификатор сессии Telegram auth. Передавайте его в status endpoint."
    )
    status = serializers.ChoiceField(
        choices=TELEGRAM_AUTH_STATUSES,
        help_text="Начальный статус всегда pending.",
    )
    bot_link = serializers.CharField(
        help_text="Deep-link в Telegram-бота вида https://t.me/<bot>?start=<session_id>."
    )
    expires_in = serializers.IntegerField(
        help_text="TTL сессии в секундах."
    )


class TelegramAuthStatusRequestSerializer(serializers.Serializer):
    session_id = serializers.CharField(
        help_text="session_id, полученный из /telegram/auth/start/."
    )


class TelegramAuthStatusResponseSerializer(serializers.Serializer):
    status = serializers.ChoiceField(
        choices=TELEGRAM_AUTH_STATUSES,
        help_text=(
            "pending - ожидается переход в бота; "
            "waiting_contact - ожидается контакт; "
            "completed - авторизация подтверждена."
        ),
    )
    refresh = serializers.CharField(
        required=False,
        help_text="JWT refresh token. Возвращается только при status=completed.",
    )
    access = serializers.CharField(
        required=False,
        help_text="JWT access token. Возвращается только при status=completed.",
    )
    stream_token = serializers.CharField(
        required=False,
        help_text="Токен Stream chat. Возвращается только при status=completed.",
    )


class TelegramAuthErrorResponseSerializer(serializers.Serializer):
    detail = serializers.CharField()
