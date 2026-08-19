"""Единый формат ошибок API.

Каждая ошибка, которая уходит клиенту, содержит машинночитаемый `code`
и человекочитаемый `message`. Клиент реагирует на `code`, а `message`
показывает пользователю (или подменяет своим переводом).

Формат ответа:

    {
        "code": "OTP_CODE_INVALID",
        "message": "Неверный код",
        "detail": "Неверный код",          # для обратной совместимости
        "errors": {"phone_number": [...]},  # только для ошибок валидации
        ...                                  # доп. поля конкретной ошибки
    }

Ключи ответа проходят через CamelCaseJSONRenderer, поэтому на клиенте это
`code`, `message`, `detail`, `errors`, `secondsLeft` и т.д.
"""

from rest_framework import status
from rest_framework.exceptions import APIException
from rest_framework.response import Response


class ErrorCode:
    """Все коды ошибок API. Значение кода — часть публичного контракта."""

    # --- Общие ---
    VALIDATION_ERROR = "VALIDATION_ERROR"
    PARSE_ERROR = "PARSE_ERROR"
    PARAM_REQUIRED = "PARAM_REQUIRED"
    PARAM_INVALID = "PARAM_INVALID"
    NOT_AUTHENTICATED = "NOT_AUTHENTICATED"
    PERMISSION_DENIED = "PERMISSION_DENIED"
    NOT_FOUND = "NOT_FOUND"
    METHOD_NOT_ALLOWED = "METHOD_NOT_ALLOWED"
    NOT_ACCEPTABLE = "NOT_ACCEPTABLE"
    UNSUPPORTED_MEDIA_TYPE = "UNSUPPORTED_MEDIA_TYPE"
    CONFLICT = "CONFLICT"
    THROTTLED = "THROTTLED"
    INTERNAL_ERROR = "INTERNAL_ERROR"
    SERVICE_UNAVAILABLE = "SERVICE_UNAVAILABLE"
    UPSTREAM_ERROR = "UPSTREAM_ERROR"

    # --- Авторизация / токены ---
    TOKEN_INVALID = "TOKEN_INVALID"
    TOKEN_EXPIRED = "TOKEN_EXPIRED"
    TOKEN_REVOKED = "TOKEN_REVOKED"  # вошли с другого устройства
    INVALID_CREDENTIALS = "INVALID_CREDENTIALS"
    ACCOUNT_NOT_ACTIVATED = "ACCOUNT_NOT_ACTIVATED"

    # --- OTP ---
    OTP_SEND_FAILED = "OTP_SEND_FAILED"
    OTP_SEND_COOLDOWN = "OTP_SEND_COOLDOWN"
    OTP_SMS_RESEND_COOLDOWN = "OTP_SMS_RESEND_COOLDOWN"
    OTP_CODE_INVALID = "OTP_CODE_INVALID"
    OTP_CODE_EXPIRED = "OTP_CODE_EXPIRED"

    # --- Telegram ---
    TELEGRAM_SESSION_NOT_FOUND = "TELEGRAM_SESSION_NOT_FOUND"
    TELEGRAM_SESSION_ALREADY_USED = "TELEGRAM_SESSION_ALREADY_USED"
    INVALID_WEBHOOK_SECRET = "INVALID_WEBHOOK_SECRET"

    # --- Чаты ---
    CHAT_NOT_FOUND = "CHAT_NOT_FOUND"
    SPECIALIST_ONLY = "SPECIALIST_ONLY"
    CHAT_CHANNEL_MISMATCH = "CHAT_CHANNEL_MISMATCH"
    STREAM_CHANNEL_CREATE_FAILED = "STREAM_CHANNEL_CREATE_FAILED"
    STREAM_CHANNEL_UPDATE_FAILED = "STREAM_CHANNEL_UPDATE_FAILED"

    # --- Подписки и оплата ---
    TARIFF_NOT_FOUND = "TARIFF_NOT_FOUND"
    FREE_TARIFF_ACTIVE = "FREE_TARIFF_ACTIVE"
    FREE_TARIFF_ALREADY_USED = "FREE_TARIFF_ALREADY_USED"
    PAYMENT_LINK_FAILED = "PAYMENT_LINK_FAILED"
    SUBSCRIPTION_NOT_ACTIVE = "SUBSCRIPTION_NOT_ACTIVE"
    SUBSCRIPTION_NOT_FOUND = "SUBSCRIPTION_NOT_FOUND"
    ACCESS_ORDER_NOT_FOUND = "ACCESS_ORDER_NOT_FOUND"
    ORDER_NOT_FOUND = "ORDER_NOT_FOUND"

    # --- Интеграции (NewCRM / MedCRM / SSO) ---
    ORGANIZATION_NOT_FOUND = "ORGANIZATION_NOT_FOUND"
    SPECIALIST_NOT_FOUND = "SPECIALIST_NOT_FOUND"
    CLIENT_NOT_FOUND = "CLIENT_NOT_FOUND"
    CLIENT_NOT_LINKED_TO_NEWCRM = "CLIENT_NOT_LINKED_TO_NEWCRM"
    CONCLUSION_NOT_FOUND = "CONCLUSION_NOT_FOUND"
    NEWCRM_ERROR = "NEWCRM_ERROR"
    NEWCRM_UNAVAILABLE = "NEWCRM_UNAVAILABLE"
    SSO_NOT_CONFIGURED = "SSO_NOT_CONFIGURED"
    SSO_TOKEN_INVALID = "SSO_TOKEN_INVALID"
    PHONE_NUMBER_MISSING = "PHONE_NUMBER_MISSING"
    INVALID_INTEGRATION_SECRET = "INVALID_INTEGRATION_SECRET"


# Коды по умолчанию для стандартных статусов DRF.
DEFAULT_CODE_BY_STATUS = {
    status.HTTP_400_BAD_REQUEST: ErrorCode.VALIDATION_ERROR,
    status.HTTP_401_UNAUTHORIZED: ErrorCode.NOT_AUTHENTICATED,
    status.HTTP_403_FORBIDDEN: ErrorCode.PERMISSION_DENIED,
    status.HTTP_404_NOT_FOUND: ErrorCode.NOT_FOUND,
    status.HTTP_405_METHOD_NOT_ALLOWED: ErrorCode.METHOD_NOT_ALLOWED,
    status.HTTP_406_NOT_ACCEPTABLE: ErrorCode.NOT_ACCEPTABLE,
    status.HTTP_409_CONFLICT: ErrorCode.CONFLICT,
    status.HTTP_415_UNSUPPORTED_MEDIA_TYPE: ErrorCode.UNSUPPORTED_MEDIA_TYPE,
    status.HTTP_429_TOO_MANY_REQUESTS: ErrorCode.THROTTLED,
    status.HTTP_500_INTERNAL_SERVER_ERROR: ErrorCode.INTERNAL_ERROR,
    status.HTTP_502_BAD_GATEWAY: ErrorCode.UPSTREAM_ERROR,
    status.HTTP_503_SERVICE_UNAVAILABLE: ErrorCode.SERVICE_UNAVAILABLE,
}


def default_code_for_status(status_code):
    if status_code in DEFAULT_CODE_BY_STATUS:
        return DEFAULT_CODE_BY_STATUS[status_code]
    if 500 <= (status_code or 0):
        return ErrorCode.INTERNAL_ERROR
    return ErrorCode.VALIDATION_ERROR


def error_payload(code, message, errors=None, **extra):
    """Собирает тело ошибки в едином формате."""
    payload = {
        "code": code,
        "message": message,
        # `detail` оставлен ради клиентов, которые уже читают это поле
        "detail": message,
    }
    if errors is not None:
        payload["errors"] = errors
    # доп. поля не должны перетирать сам код ошибки
    for key, value in extra.items():
        if key in ("code", "message"):
            continue
        payload.setdefault(key, value)
    return payload


def error_response(code, message, status_code=status.HTTP_400_BAD_REQUEST, errors=None, **extra):
    """Ответ с ошибкой в едином формате."""
    return Response(
        error_payload(code, message, errors=errors, **extra),
        status=status_code,
    )


class AppError(APIException):
    """Ошибка приложения с машинночитаемым кодом.

    Обрабатывается `common.error_handler.api_exception_handler`, поэтому её
    можно бросать из сервисов и сериализаторов.
    """

    status_code = status.HTTP_400_BAD_REQUEST
    error_code = ErrorCode.VALIDATION_ERROR
    default_detail = "Ошибка запроса"

    def __init__(self, message=None, code=None, status_code=None, errors=None, **extra):
        self.error_code = code or self.error_code
        if status_code is not None:
            self.status_code = status_code
        self.errors = errors
        self.extra = extra
        super().__init__(message or self.default_detail)
