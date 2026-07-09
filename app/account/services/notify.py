import logging
from typing import Optional

import requests
from django.conf import settings

logger = logging.getLogger(__name__)

RAVEN_API_URL = settings.RAVEN_API_URL.rstrip("/")
RAVEN_API_KEY = settings.RAVEN_API_KEY
RAVEN_TIMEOUT = 10  # секунд


def send_notification(
    phone: str,
    scenario: str,
    variables: Optional[dict] = None,
    external_id: Optional[str] = None,
    idempotency_key: Optional[str] = None,
    return_meta: bool = False,
):
    """Отправляет уведомление через Raven (https://raven.operator.kg) по коду сценария."""
    payload = {
        "scenario": scenario,
        "recipient": phone,
        "variables": variables or {},
    }
    if external_id:
        payload["external_id"] = external_id
    if idempotency_key:
        payload["idempotency_key"] = idempotency_key

    headers = {
        "Authorization": f"Bearer {RAVEN_API_KEY}",
        "Content-Type": "application/json",
    }

    def _fail(status_code, provider_status, provider_response, error_message, message_id=None):
        logger.warning(
            f"[RAVEN ERROR] Статус: {status_code}, Телефон: {phone}, Сценарий: {scenario}, Ошибка: {error_message}"
        )
        if return_meta:
            return {
                "ok": False,
                "status_code": status_code,
                "provider_status": provider_status,
                "provider_message_id": message_id or "",
                "provider_response": provider_response,
                "transaction_id": message_id,
                "error_message": error_message,
            }
        return False

    try:
        response = requests.post(
            f"{RAVEN_API_URL}/messages/",
            json=payload,
            headers=headers,
            timeout=RAVEN_TIMEOUT,
        )
    except requests.RequestException as e:
        return _fail(None, "", "", str(e))

    if response.status_code != 202:
        try:
            error = response.json().get("error", {})
        except ValueError:
            error = {}
        return _fail(
            response.status_code,
            error.get("code", ""),
            response.text,
            error.get("message") or f"HTTP {response.status_code}",
        )

    data = response.json()
    message_id = data.get("message_id", "")
    logger.info(f"[RAVEN OK] Уведомление отправлено на {phone}, сценарий: {scenario}, message_id: {message_id}")
    if return_meta:
        return {
            "ok": True,
            "status_code": response.status_code,
            "provider_status": data.get("status", ""),
            "provider_message_id": message_id,
            "provider_response": response.text,
            "transaction_id": message_id,
            "error_message": "",
        }
    return True
