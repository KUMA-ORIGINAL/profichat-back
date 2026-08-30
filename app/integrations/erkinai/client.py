"""HTTP-клиент справочника ErkinAI (входящая часть интеграции NewCRM).

Отличается от :mod:`integrations.mamadoc.client` тем, чем авторизуется. Тот
ходит партнёрским Bearer-ключом от имени одной клиники; здесь же запросы
межсервисные и авторизуются общим секретом ``MEDCRM_SSO_INTEGRATION_SECRET`` в
заголовке ``X-Integration-Secret`` — тем самым, которым ErkinAI проверяет у нас
одноразовые SSO-токены. Секрет один на всю интеграцию в обе стороны.

Две ручки:

* ``lookup_staff_by_phone`` — есть ли в ErkinAI карточка сотрудника с таким
  номером. Зовём при регистрации, когда номер уже подтверждён по SMS.
* ``fetch_organizations`` — постраничный фид организаций, из которого мы держим
  свой справочник в актуальном состоянии.

Секрет живёт только здесь, на бэкенде: в приложение он не уезжает никогда.
"""

import logging
from typing import Optional

import requests
from django.conf import settings

logger = logging.getLogger(__name__)

STAFF_LOOKUP_PATH = "/api/integration/profichat/staff-lookup/"
ORGANIZATIONS_PATH = "/api/integration/profichat/organizations/"

# Страховка от бесконечного цикла, если ErkinAI однажды начнёт отдавать
# nextCursor, который никуда не двигается.
MAX_PAGES = 1000


class ErkinAIError(Exception):
    """ErkinAI недоступен, не настроен или ответил непонятно."""

    def __init__(self, message, status_code=None):
        self.status_code = status_code
        super().__init__(message)


class ErkinAIDisabled(ErkinAIError):
    """Интеграция выключена на стенде ErkinAI (404) или не настроена у нас.

    Отдельный класс, потому что это не поломка: вызывающий код должен просто
    продолжить без ErkinAI, а не показывать ошибку.
    """


def is_configured() -> bool:
    """Есть ли чем и куда ходить."""
    return bool(_base_url() and _secret())


def lookup_staff_by_phone(phone: str) -> list:
    """Карточки сотрудников ErkinAI с номером *phone* (пустой список — нет).

    Пустой список — штатный исход, а не ошибка: большинство регистрирующихся
    не работают ни в одной клинике на ErkinAI.
    """
    payload = _request("POST", STAFF_LOOKUP_PATH, json_data={"phone": phone})
    employees = payload.get("employees")
    return employees if isinstance(employees, list) else []


def fetch_organizations(updated_since: Optional[str] = None, limit: int = 100):
    """Все организации фида плюс ``syncedAt`` последнего ответа.

    ``syncedAt`` — то, что нужно сохранить как ``updated_since`` следующего
    запуска. Берётся из последней страницы: ErkinAI снимает его до выборки,
    поэтому правки, случившиеся во время обхода, попадут в следующий заход, а
    не провалятся в щель между строкой и часами.
    """
    organizations = []
    synced_at = None
    for organization, page_synced_at in _walk_organizations(updated_since, limit):
        organizations.append(organization)
        synced_at = page_synced_at
    return organizations, synced_at


def _walk_organizations(updated_since, limit):
    cursor = None
    for _ in range(MAX_PAGES):
        params = {"limit": limit}
        if updated_since:
            params["updated_since"] = updated_since
        if cursor:
            params["cursor"] = cursor

        payload = _request("GET", ORGANIZATIONS_PATH, params=params)
        synced_at = payload.get("syncedAt")
        for organization in payload.get("organizations") or []:
            yield organization, synced_at

        cursor = payload.get("nextCursor")
        if not cursor:
            return

    raise ErkinAIError("ErkinAI отдаёт страницы организаций без конца.")


def _base_url() -> str:
    return str(getattr(settings, "MAMADOC_API_URL", "") or "").rstrip("/")


def _secret() -> str:
    return str(getattr(settings, "MEDCRM_SSO_INTEGRATION_SECRET", "") or "")


def _timeout() -> int:
    return int(getattr(settings, "MAMADOC_TIMEOUT", 10))


def _request(method: str, path: str, *, params=None, json_data=None) -> dict:
    if not is_configured():
        raise ErkinAIDisabled("Интеграция с ErkinAI не настроена.")

    url = f"{_base_url()}{path}"
    headers = {
        "X-Integration-Secret": _secret(),
        "Content-Type": "application/json",
    }

    try:
        response = requests.request(
            method, url, params=params, json=json_data, headers=headers, timeout=_timeout()
        )
    except requests.RequestException as exc:
        logger.warning("[ERKINAI] %s %s: %s", method, path, exc)
        raise ErkinAIError(f"Нет связи с ErkinAI: {exc}")

    # 404 здесь означает «интеграция выключена на стенде», а не «не найдено»:
    # обе ручки на «не найдено» отвечают 200 с пустым результатом.
    if response.status_code == 404:
        raise ErkinAIDisabled("Интеграция с ErkinAI выключена на стороне CRM.")
    if not response.ok:
        logger.warning(
            "[ERKINAI] %s %s: HTTP %s %s", method, path, response.status_code, response.text[:500]
        )
        raise ErkinAIError(
            f"ErkinAI ответил HTTP {response.status_code}", status_code=response.status_code
        )

    try:
        payload = response.json()
    except ValueError:
        raise ErkinAIError("ErkinAI вернул не-JSON.")

    if not isinstance(payload, dict):
        raise ErkinAIError("ErkinAI вернул неожиданную структуру ответа.")
    return payload
