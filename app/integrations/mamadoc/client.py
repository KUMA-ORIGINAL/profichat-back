import logging
from typing import Optional

import requests
from django.conf import settings

logger = logging.getLogger(__name__)

MAMADOC_API_URL = settings.MAMADOC_API_URL.rstrip("/")
MAMADOC_API_KEY = settings.MAMADOC_API_KEY
MAMADOC_TIMEOUT = settings.MAMADOC_TIMEOUT


def _headers():
    return {
        "Authorization": f"Bearer {MAMADOC_API_KEY}",
        "Content-Type": "application/json",
    }


def _get(path, params=None):
    if not MAMADOC_API_URL:
        logger.warning("[MAMADOC] MAMADOC_API_URL не настроен, запрос пропущен: %s", path)
        return None

    try:
        response = requests.get(
            f"{MAMADOC_API_URL}{path}",
            params=params,
            headers=_headers(),
            timeout=MAMADOC_TIMEOUT,
        )
    except requests.RequestException as e:
        logger.warning("[MAMADOC ERROR] %s params=%s: %s", path, params, e)
        return None

    if response.status_code == 404:
        return None
    if not response.ok:
        logger.warning(
            "[MAMADOC ERROR] %s params=%s: HTTP %s %s", path, params, response.status_code, response.text
        )
        return None

    try:
        return response.json()
    except ValueError:
        logger.warning("[MAMADOC ERROR] Невалидный JSON от %s", path)
        return None


def find_patient_id_by_phone(phone: str) -> Optional[str]:
    """
    Ищет пациента MamaDoc по номеру телефона.

    Номер телефона в MamaDoc не уникален — при нескольких совпадениях
    берётся первая запись из ответа (см. открытые вопросы к команде MamaDoc).
    """
    data = _get("/api/patients/", params={"search": phone})
    if not data:
        return None

    results = data.get("results", data) if isinstance(data, dict) else data
    if not results:
        return None

    return results[0].get("id")


def find_employee_id_by_phone(phone: str) -> Optional[str]:
    """
    Ищет сотрудника (врача) MamaDoc по номеру телефона специалиста Профиграма.

    Используется, чтобы определить employee_id специалиста по его собственному
    номеру телефона, а не доверять employee_id, присланному с клиента.
    """
    data = _get("/api/staff/employees/", params={"search": phone})
    if not data:
        return None

    results = data.get("results", data) if isinstance(data, dict) else data
    if not results:
        return None

    return results[0].get("id")


def list_appointments(patient_id) -> list:
    """Возвращает визиты пациента, у которых есть строки услуг (serviceLines)."""
    data = _get("/api/appointments/", params={"patientId": patient_id})
    if not data:
        return []

    appointments = data.get("results", data) if isinstance(data, dict) else data
    if not appointments:
        return []

    return [a for a in appointments if a.get("serviceLines")]


def get_conclusion(conclusion_id) -> Optional[dict]:
    """Возвращает детальные данные медицинского заключения по id."""
    return _get(f"/api/medical/conclusions/{conclusion_id}/")


def list_employee_appointments(employee_id, start_date=None, end_date=None, status=None) -> list:
    """Возвращает брони (записи) специалиста в MamaDoc."""
    params = {"employeeId": employee_id}
    if start_date:
        params["dateFrom"] = start_date
    if end_date:
        params["dateTo"] = end_date
    if status:
        params["status"] = status

    data = _get("/api/appointments/", params=params)
    if not data:
        return []

    return data.get("results", data) if isinstance(data, dict) else data


class MamaDocAPIError(Exception):
    """Ошибка при обращении к MamaDoc API. `status_code` — что вернуть клиенту Профиграма."""

    def __init__(self, status_code, detail):
        self.status_code = status_code
        self.detail = detail
        super().__init__(detail)


def _post(path, json_data):
    if not MAMADOC_API_URL:
        logger.warning("[MAMADOC] MAMADOC_API_URL не настроен, запрос пропущен: %s", path)
        raise MamaDocAPIError(502, "MamaDoc API не настроен.")

    try:
        response = requests.post(
            f"{MAMADOC_API_URL}{path}",
            json=json_data,
            headers=_headers(),
            timeout=MAMADOC_TIMEOUT,
        )
    except requests.RequestException as e:
        logger.warning("[MAMADOC ERROR] POST %s: %s", path, e)
        raise MamaDocAPIError(502, "Ошибка соединения с MamaDoc.")

    if response.status_code in (400, 422):
        raise MamaDocAPIError(400, _safe_json(response) or response.text)
    if not response.ok:
        logger.warning(
            "[MAMADOC ERROR] POST %s: HTTP %s %s", path, response.status_code, response.text
        )
        raise MamaDocAPIError(502, "Ошибка ответа MamaDoc.")

    return _safe_json(response)


def _safe_json(response):
    try:
        return response.json()
    except ValueError:
        return None


def create_appointment(branch_id, patient_id, employee_id, service_id, starts_at_iso, status="scheduled") -> dict:
    """
    Создаёт запись (бронь) в MamaDoc.

    `starts_at_iso` должен быть уже нормализован в UTC (например, `...T10:00:00Z`).
    """
    payload = {
        "branchId": branch_id,
        "patientId": patient_id,
        "startsAt": starts_at_iso,
        "status": status,
        "services": [{"serviceId": service_id, "employeeId": employee_id}],
    }
    return _post("/api/appointments/", payload)
