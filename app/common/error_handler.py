"""Обработчик исключений DRF: гарантирует `code` в любом ответе с ошибкой."""

import logging

from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import status
from rest_framework.exceptions import (
    APIException,
    AuthenticationFailed,
    NotAuthenticated,
    ValidationError,
)
from rest_framework.response import Response
from rest_framework.views import exception_handler as drf_exception_handler
from rest_framework_simplejwt.exceptions import InvalidToken, TokenError

from common.errors import AppError, ErrorCode, default_code_for_status, error_payload

logger = logging.getLogger(__name__)

# Соответствие `code` из DRF/SimpleJWT нашим кодам.
_DRF_CODE_MAP = {
    "authentication_failed": ErrorCode.TOKEN_INVALID,
    "not_authenticated": ErrorCode.NOT_AUTHENTICATED,
    "permission_denied": ErrorCode.PERMISSION_DENIED,
    "not_found": ErrorCode.NOT_FOUND,
    "method_not_allowed": ErrorCode.METHOD_NOT_ALLOWED,
    "not_acceptable": ErrorCode.NOT_ACCEPTABLE,
    "unsupported_media_type": ErrorCode.UNSUPPORTED_MEDIA_TYPE,
    "throttled": ErrorCode.THROTTLED,
    "parse_error": ErrorCode.PARSE_ERROR,
    "invalid": ErrorCode.VALIDATION_ERROR,
}


def _first_message(detail, fallback):
    """Достаёт первое человекочитаемое сообщение из detail любой формы."""
    if isinstance(detail, dict):
        for key, value in detail.items():
            message = _first_message(value, None)
            if message:
                return message if key == "detail" else f"{key}: {message}"
        return fallback
    if isinstance(detail, (list, tuple)):
        for item in detail:
            message = _first_message(item, None)
            if message:
                return message
        return fallback
    if detail in (None, ""):
        return fallback
    return str(detail)


def _token_error_code(detail_str):
    lowered = detail_str.lower()
    if "blacklisted" in lowered:
        return ErrorCode.TOKEN_REVOKED, "Вы вошли с другого устройства"
    if "expired" in lowered:
        return ErrorCode.TOKEN_EXPIRED, "Срок действия токена истёк"
    if "invalid" in lowered or "token" in lowered:
        return ErrorCode.TOKEN_INVALID, "Некорректный токен"
    return ErrorCode.NOT_AUTHENTICATED, "Ошибка авторизации"


# Старые значения `reason`, которые уже читают клиенты, — оставляем для совместимости.
_LEGACY_REASON_BY_CODE = {
    ErrorCode.TOKEN_REVOKED: "logged_in_from_another_device",
    ErrorCode.TOKEN_EXPIRED: "token_expired",
    ErrorCode.TOKEN_INVALID: "invalid_token",
    ErrorCode.NOT_AUTHENTICATED: "unknown",
}


def _legacy_first(payload, legacy):
    """Ставит legacy-поля в начало тела: клиенты, которые берут первую ошибку из ответа,
    по-прежнему получают ошибку поля, а не служебный `code`."""
    extra = {key: value for key, value in legacy.items() if key not in payload}
    return {**extra, **payload}


def api_exception_handler(exc, context):
    # Ошибки авторизации: отдельный ответ, чтобы сохранить поля error/reason/message
    if isinstance(exc, (InvalidToken, TokenError, AuthenticationFailed, NotAuthenticated)):
        detail_str = _first_message(getattr(exc, "detail", None), "") or str(exc)
        code, message = _token_error_code(detail_str)
        if isinstance(exc, NotAuthenticated):
            code = ErrorCode.NOT_AUTHENTICATED
            # текст оставляем как у DRF — его уже показывают клиенты
            message = detail_str or "Требуется авторизация"
        return Response(
            error_payload(
                code,
                message,
                # legacy-поля прежнего формата 401
                error="Unauthorized",
                reason=_LEGACY_REASON_BY_CODE.get(code, "unknown"),
            ),
            status=status.HTTP_401_UNAUTHORIZED,
        )

    # Django-валидация (например, из model.save()) иначе превратилась бы в 500 без кода
    if isinstance(exc, DjangoValidationError):
        messages = getattr(exc, "messages", None) or [str(exc)]
        return Response(
            error_payload(
                ErrorCode.VALIDATION_ERROR,
                messages[0],
                errors=getattr(exc, "message_dict", None) or messages,
            ),
            status=status.HTTP_400_BAD_REQUEST,
        )

    if isinstance(exc, AppError):
        payload = error_payload(
            exc.error_code,
            _first_message(exc.detail, "Ошибка запроса"),
            errors=exc.errors,
            **exc.extra,
        )
        # поля остаются и на верхнем уровне — старые клиенты читают их оттуда
        if isinstance(exc.errors, dict):
            payload = _legacy_first(payload, exc.errors)
        return Response(payload, status=exc.status_code)

    response = drf_exception_handler(exc, context)
    if response is None:
        # Необработанное исключение — DRF отдаст 500 сам, но клиент должен получить код
        logger.exception("Unhandled exception in %s", context.get("view"))
        return Response(
            error_payload(ErrorCode.INTERNAL_ERROR, "Внутренняя ошибка сервера"),
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    detail = getattr(exc, "detail", None)

    if isinstance(exc, ValidationError):
        errors = detail if isinstance(detail, (dict, list)) else {"detail": detail}
        payload = error_payload(
            ErrorCode.VALIDATION_ERROR,
            _first_message(detail, "Некорректные данные"),
            errors=errors,
        )
    else:
        drf_code = getattr(exc, "default_code", None)
        code = _DRF_CODE_MAP.get(drf_code) or default_code_for_status(response.status_code)
        payload = error_payload(code, _first_message(detail, "Ошибка запроса"))
        if isinstance(detail, (dict, list)):
            payload["errors"] = detail

    # Не теряем поля, которые DRF положил в ответ (ошибки по полям, wait у Throttled)
    if isinstance(response.data, dict):
        payload = _legacy_first(payload, response.data)

    response.data = payload
    return response


def app_error_from_api_exception(exc: APIException, code):
    """Утилита: превращает APIException в AppError с нужным кодом."""
    return AppError(
        _first_message(getattr(exc, "detail", None), "Ошибка запроса"),
        code=code,
        status_code=exc.status_code,
    )
