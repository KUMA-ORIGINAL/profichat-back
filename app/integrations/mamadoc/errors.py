"""Преобразование ошибок NewCRM (MamaDoc) в ответ клиенту с кодом."""

import logging

from common.errors import ErrorCode, error_response

from .client import MamaDocAPIError

logger = logging.getLogger(__name__)


def mamadoc_error_response(exc: MamaDocAPIError):
    """Ответ клиенту по ошибке NewCRM: 502 — связь/конфигурация, иначе ошибка самого API."""
    logger.warning("NewCRM request failed: %s", exc.detail)

    code = (
        ErrorCode.NEWCRM_UNAVAILABLE
        if exc.status_code in (502, 503, 504)
        else ErrorCode.NEWCRM_ERROR
    )

    detail = exc.detail
    if isinstance(detail, dict):
        message = detail.get("detail") or detail.get("message") or "Ошибка при обращении к NewCRM."
        extra = {"errors": detail}
    elif isinstance(detail, list):
        message = "Ошибка при обращении к NewCRM."
        extra = {"errors": detail}
    else:
        message = str(detail)
        extra = {}

    if not isinstance(message, str):
        message = "Ошибка при обращении к NewCRM."

    response = error_response(code, message, exc.status_code, **extra)

    # NewCRM отдаёт `detail` списком объектов {msg, type} — сохраняем исходную форму,
    # клиенты разбирают её как раньше
    if isinstance(detail, dict):
        response.data.update(detail)
    elif isinstance(detail, list):
        response.data["detail"] = detail

    return response
