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

    if 400 <= response.status_code < 500:
        raise MamaDocAPIError(response.status_code, _safe_json(response) or response.text)
    if not response.ok:
        logger.warning(
            "[MAMADOC ERROR] PATCH %s: HTTP %s %s", path, response.status_code, response.text
        )
        raise MamaDocAPIError(502, "Ошибка ответа MamaDoc.")

    return _safe_json(response)


def _normalize_phone(phone) -> str:
    return "".join(ch for ch in str(phone or "") if ch.isdigit())


def find_patient_id_by_phone(phone: str) -> Optional[str]:
    """
    Ищет пациента MamaDoc по номеру телефона.

    `/api/patients/?search=` в MamaDoc matчит ПОДСТРОКУ номера (icontains),
    а не точное совпадение — неполный/усечённый номер может найти сразу
    нескольких разных пациентов. Поэтому здесь принимается только тот
    результат, чей номер телефона совпадает с запрошенным ТОЧНО (после
    нормализации цифр) — иначе можно случайно вернуть чужого пациента.

    Пробелы/скобки/дефисы в номере убираются перед поиском — MamaDoc ищет
    буквально по подстроке, и "+996 550 365 790" не совпадёт с хранимым
    "+996550365790", хотя цифры идентичны.

    Если после очистки цифр почти не осталось (мусорный ввод вроде "" или
    "<script>"), поиск не отправляется вообще: пустая/короткая search-строка
    матчит ЛЮБУЮ подстроку в MamaDoc (т.е. вообще всех пациентов организации)
    — это и лишняя нагрузка, и риск случайного совпадения с пациентом без
    указанного телефона.
    """
    target = _normalize_phone(phone)
    if len(target) < 4:
        return None

    search_phone = "".join(ch for ch in str(phone or "") if ch.isdigit() or ch == "+")
    data = _get("/api/patients/", params={"search": search_phone})
    if not data:
        return None

    results = data.get("results", data) if isinstance(data, dict) else data
    if not results:
        return None

    for candidate in results:
        if _normalize_phone(candidate.get("phone")) == target:
            return candidate.get("id")

    return None


def list_professionals(organization_id) -> list:
    """
    Возвращает публичный каталог врачей клиники NewCRM (id, ФИО, фото,
    специальность) — используется, чтобы найти employeeId нужного врача.

    Эндпоинт `/api/v1/professionals/` в NewCRM публичный (не требует
    авторизации), в отличие от `/api/staff/employees/`.
    """
    data = _get("/api/v1/professionals/", params={"organization_id": organization_id})
    if not data:
        return []

    return data.get("data", data) if isinstance(data, dict) else data


def list_services(organization_id) -> list:
    """
    Возвращает публичный каталог услуг клиники NewCRM (id, название, цена,
    длительность) — используется, чтобы показать стоимость перед созданием брони.

    Эндпоинт `/api/v1/organizations/{id}/services/` в NewCRM публичный.
    """
    data = _get(f"/api/v1/organizations/{organization_id}/services/")
    if not data:
        return []

    return data.get("data", data) if isinstance(data, dict) else data


def get_organization() -> Optional[dict]:
    """
    Возвращает клинику, привязанную к текущему партнёрскому ключу.

    Требует право `organization.view`. Реальный ответ NewCRM — список из
    одного объекта; здесь отдаётся сразу этот объект (или None).
    """
    data = _get("/api/organization/")
    if not data:
        return None

    results = data.get("results", data) if isinstance(data, dict) else data
    if not results:
        return None

    return results[0]


def list_branches() -> list:
    """Возвращает филиалы клиники, привязанной к ключу. Требует право `branches.view`."""
    data = _get("/api/organization/branches/")
    if not data:
        return []

    return data.get("results", data) if isinstance(data, dict) else data


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


def create_booking(branch_id, employee_id, service_id, date, time, first_name, last_name, phone) -> dict:
    """
    Создаёт запись (бронь) через партнёрский эндпоинт `/api/profigram/bookings/`.

    Пациент ищется по номеру телефона и создаётся автоматически, если не найден
    (дедуп на стороне NewCRM). Цену NewCRM определяет сама по `service_id` —
    клиент не может её подменить.

    `date` — 'YYYY-MM-DD', `time` — 'HH:MM'.
    """
    payload = {
        "branchId": branch_id,
        "employeeId": employee_id,
        "serviceId": service_id,
        "date": date,
        "time": time,
        "patientFirstName": first_name,
        "patientLastName": last_name,
        "patientPhone": phone,
    }
    return _post("/api/profigram/bookings/", payload)


def cancel_booking(booking_id, reason="") -> dict:
    """Отменяет запись через партнёрский эндпоинт `/api/profigram/bookings/{id}/cancel/`."""
    return _patch(f"/api/profigram/bookings/{booking_id}/cancel/", {"reason": reason})
