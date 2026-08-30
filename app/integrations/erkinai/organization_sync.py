"""Зеркалирование справочника организаций ErkinAI в наш.

Источник правды — ErkinAI, мы держим копию. Запускается командой
``manage.py sync_erkinai_organizations`` (по крону).

Что важно в этой логике:

* **Апсерт по ``erkinai_id``, а не по имени.** Имя организации у нас уникально
  и его правят руками; сопоставление по нему при первом же переименовании
  создало бы дубль.
* **Организации, заведённые в ProfiChat вручную, не трогаем.** Синхронизация
  видит только те, у кого проставлен ``erkinai_id``, — свои живут своей жизнью.
* **Неактивная в ErkinAI гасится, а не удаляется.** На неё могут ссылаться
  профили специалистов; удаление порвало бы их. К тому же организацию могут
  расснять с архива, и тогда она вернётся сама.
* **Адреса заводятся из филиалов** и держатся по ``erkinai_branch_id``. Филиал,
  пропавший из фида, свой адрес забирает с собой — иначе у организации вечно
  копились бы адреса закрытых точек.
"""

import logging

from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from account.models import Organization, OrganizationAddress
from integrations.erkinai import client
from integrations.models import ErkinAISyncState

logger = logging.getLogger(__name__)


class SyncResult:
    """Что сделал один запуск — для лога и вывода команды."""

    def __init__(self):
        self.created = 0
        self.updated = 0
        self.deactivated = 0
        self.skipped = 0
        self.synced_at = None

    @property
    def total(self):
        return self.created + self.updated

    def __str__(self):
        return (
            f"создано {self.created}, обновлено {self.updated}, "
            f"погашено {self.deactivated}, пропущено {self.skipped}"
        )


def sync_organizations(*, full: bool = False) -> SyncResult:
    """Забирает изменения из ErkinAI и применяет их к нашему справочнику.

    ``full=True`` — полный проход без окна. Нужен периодически (скажем, раз в
    сутки): фид не умеет сообщать о жёстком удалении, и только полный проход
    подберёт исчезнувшие филиалы.
    """
    state, _ = ErkinAISyncState.objects.get_or_create(
        feed=ErkinAISyncState.FEED_ORGANIZATIONS
    )
    updated_since = None if full else _isoformat(state.synced_at)

    organizations, synced_at = client.fetch_organizations(updated_since=updated_since)

    result = SyncResult()
    for payload in organizations:
        _apply_one(payload, result)

    result.synced_at = parse_datetime(synced_at) if synced_at else None
    # Отметку двигаем только после полного успешного обхода: обход бросает
    # исключение на первой же неудачной странице, и тогда сюда мы не дойдём —
    # следующий запуск честно начнёт с прежней точки.
    if result.synced_at is not None:
        state.synced_at = result.synced_at
    state.last_run_at = timezone.now()
    state.save(update_fields=["synced_at", "last_run_at", "updated_at"])

    logger.info("[ERKINAI] Синхронизация организаций: %s", result)
    return result


@transaction.atomic
def _apply_one(payload: dict, result: SyncResult) -> None:
    erkinai_id = payload.get("id")
    name = (payload.get("name") or "").strip()
    if not erkinai_id or not name:
        result.skipped += 1
        logger.warning("[ERKINAI] Организация без id или названия пропущена: %s", payload)
        return

    organization = Organization.objects.filter(erkinai_id=erkinai_id).first()
    is_active = bool(payload.get("isActive"))
    is_new = organization is None
    was_active = organization.is_active if organization else False

    if is_new:
        organization = Organization(erkinai_id=erkinai_id)

    organization.name = _unique_name(name, erkinai_id)
    organization.is_active = is_active
    organization.save()

    _sync_addresses(organization, payload.get("branches") or [])

    # Счётчики после сохранения: строка, упавшая на save, откатится вместе с
    # транзакцией, и в отчёте её быть не должно.
    if is_new:
        result.created += 1
    else:
        result.updated += 1
    if was_active and not is_active:
        result.deactivated += 1


def _sync_addresses(organization: Organization, branches: list) -> None:
    seen_branch_ids = []
    for branch in branches:
        branch_id = branch.get("id")
        address = (branch.get("address") or "").strip()
        if not branch_id or not address:
            # Филиалу без адреса показать нечего. Но и удалять уже заведённый
            # адрес из-за того, что поле опустело, не надо — считаем, что
            # филиал по-прежнему наш.
            if branch_id:
                seen_branch_ids.append(branch_id)
            continue
        seen_branch_ids.append(branch_id)
        OrganizationAddress.objects.update_or_create(
            erkinai_branch_id=branch_id,
            defaults={"organization": organization, "address": address},
        )

    OrganizationAddress.objects.filter(
        organization=organization, erkinai_branch_id__isnull=False
    ).exclude(erkinai_branch_id__in=seen_branch_ids).delete()

    # Ровно один основной адрес: без этого карточка организации в приложении
    # покажет случайный или ни одного.
    addresses = list(organization.addresses.order_by("id"))
    if addresses and not any(row.is_primary for row in addresses):
        first = addresses[0]
        first.is_primary = True
        first.save(update_fields=["is_primary"])


def _unique_name(name: str, erkinai_id: int) -> str:
    """Имя организации у нас уникально, а в ErkinAI — нет.

    Тёзка из ErkinAI или заведённая вручную одноимённая организация — не повод
    уронить весь запуск на IntegrityError, поэтому вторая получает суффикс с id
    из ErkinAI: видный след, по которому человек разберётся.
    """
    clash = (
        Organization.objects
        .filter(name=name)
        .exclude(erkinai_id=erkinai_id)
        .exists()
    )
    if not clash:
        return name
    suffixed = f"{name} (ErkinAI #{erkinai_id})"
    logger.warning("[ERKINAI] Название «%s» занято, сохраняем как «%s»", name, suffixed)
    return suffixed[:255]


def _isoformat(value):
    return value.isoformat() if value else None
