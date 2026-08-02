import logging
from typing import Optional

import requests
from django.conf import settings
from django.utils import timezone as dj_timezone
from django.utils.dateparse import parse_datetime

logger = logging.getLogger(__name__)

MAMADOC_API_URL = settings.MAMADOC_API_URL.rstrip("/")
MAMADOC_API_KEY = settings.MAMADOC_API_KEY
MAMADOC_TIMEOUT = settings.MAMADOC_TIMEOUT

DISPLAY_DATETIME_FORMAT = "%d.%m.%Y %H:%M"

# Верхнеуровневые поля с датами, которые встречаются в "сырых" объектах NewCRM
# (appointment/conclusion) и которые стоит показывать в читаемом виде.
APPOINTMENT_DATETIME_FIELDS = ("startsAt", "endsAt", "createdAt", "updatedAt")
CONCLUSION_DATETIME_FIELDS = ("createdAt", "updatedAt")


def format_local_datetime(raw_value):
    """NewCRM отдаёт даты в UTC ISO 8601. Показываем их в местном времени в виде ДД.ММ.ГГГГ ЧЧ:ММ."""
    if not raw_value:
        return raw_value

    dt = parse_datetime(raw_value) if isinstance(raw_value, str) else raw_value
    if dt is None:
        return raw_value

    if dj_timezone.is_naive(dt):
        dt = dj_timezone.make_aware(dt, dj_timezone.utc)

    return dj_timezone.localtime(dt).strftime(DISPLAY_DATETIME_FORMAT)


def _reformat_dates(obj, fields):
    """Форматирует только перечисленные верхнеуровневые поля дат, не трогая вложенные объекты."""
    if obj is None:
        return obj
    for field in fields:
        if field in obj:
            obj[field] = format_local_datetime(obj[field])
    return obj


def reformat_appointment_dates(appointment):
    return _reformat_dates(appointment, APPOINTMENT_DATETIME_FIELDS)


def reformat_conclusion_dates(conclusion):
    return _reformat_dates(conclusion, CONCLUSION_DATETIME_FIELDS)


class MamaDocAPIError(Exception):
    """Ошибка при обращении к MamaDoc API. `status_code` — что вернуть клиенту Профиграма."""

    def __init__(self, status_code, detail):
        self.status_code = status_code
        self.detail = detail
        super().__init__(detail)


def _headers():
    return {
        "Authorization": f"Bearer {MAMADOC_API_KEY}",
        "Content-Type": "application/json",
    }


def _safe_json(response):
    try:
        return response.json()
    except ValueError:
        return None


def _get(path, params=None):
    """
    GET к MamaDoc. Возвращает None только для настоящего "не найдено" (404) —
    это ожидаемый исход для поиска (например, "нет такого пациента").
    Любая другая ошибка (сеть, 5xx, неожиданный 4xx вроде "нет прав") кидает
    MamaDocAPIError, чтобы не выглядеть как "ничего не найдено".
    """
    if not MAMADOC_API_URL:
        logger.warning("[MAMADOC] MAMADOC_API_URL не настроен, запрос пропущен: %s", path)
        raise MamaDocAPIError(502, "MamaDoc API не настроен.")

    try:
        response = requests.get(
            f"{MAMADOC_API_URL}{path}",
            params=params,
            headers=_headers(),
            timeout=MAMADOC_TIMEOUT,
        )
    except requests.RequestException as e:
        logger.warning("[MAMADOC ERROR] GET %s params=%s: %s", path, params, e)
        raise MamaDocAPIError(502, "Ошибка соединения с MamaDoc.")

    if response.status_code == 404:
        return None
    if 400 <= response.status_code < 500:
        logger.warning(
            "[MAMADOC ERROR] GET %s params=%s: HTTP %s %s", path, params, response.status_code, response.text
        )
        raise MamaDocAPIError(response.status_code, _safe_json(response) or response.text)
    if not response.ok:
        logger.warning(
            "[MAMADOC ERROR] GET %s params=%s: HTTP %s %s", path, params, response.status_code, response.text
        )
        raise MamaDocAPIError(502, "Ошибка ответа MamaDoc.")

    data = _safe_json(response)
    if data is None:
        logger.warning("[MAMADOC ERROR] Невалидный JSON от %s", path)
    return data


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

    if 400 <= response.status_code < 500:
        raise MamaDocAPIError(response.status_code, _safe_json(response) or response.text)
    if not response.ok:
        logger.warning(
            "[MAMADOC ERROR] POST %s: HTTP %s %s", path, response.status_code, response.text
        )
        raise MamaDocAPIError(502, "Ошибка ответа MamaDoc.")

    return _safe_json(response)


def _patch(path, json_data):
    if not MAMADOC_API_URL:
        logger.warning("[MAMADOC] MAMADOC_API_URL не настроен, запрос пропущен: %s", path)
        raise MamaDocAPIError(502, "MamaDoc API не настроен.")

    try:
        response = requests.patch(
            f"{MAMADOC_API_URL}{path}",
            json=json_data,
            headers=_headers(),
            timeout=MAMADOC_TIMEOUT,
        )
    except requests.RequestException as e:
        logger.warning("[MAMADOC ERROR] PATCH %s: %s", path, e)
        raise MamaDocAPIError(502, "Ошибка соединения с MamaDoc.")

    if response.status_code == 404:
        raise MamaDocAPIError(404, "Запись не найдена.")
    if 400 <= response.status_code < 500:
        raise MamaDocAPIError(response.status_code, _safe_json(response) or response.text)
    if not response.ok:
        logger.warning(
            "[MAMADOC ERROR] PATCH %s: HTTP %s %s", path, response.status_code, response.text
        )
        raise MamaDocAPIError(502, "Ошибка ответа MamaDoc.")

    return _safe_json(response)


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


def cancel_appointment(appointment_id, reason="") -> dict:
    """Отменяет запись (бронь) в MamaDoc: PATCH status=canceled."""
    payload = {"status": "canceled"}
    if reason:
        payload["cancelReason"] = reason
    return _patch(f"/api/appointments/{appointment_id}/", payload)
