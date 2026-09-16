"""Заявки на новую профессию: создание, проверка дублей, модерация."""

import logging

from django.db import transaction
from django.utils import timezone
from rest_framework import status

from common.errors import AppError, ErrorCode
from common.notifications import send_profession_request_approved_push, send_profession_request_rejected_push

logger = logging.getLogger(__name__)


class ProfessionRequestAlreadyReviewed(Exception):
    """Заявку уже рассмотрели — повторное решение не применяется."""

    def __init__(self, status):
        self.status = status
        super().__init__(f"Profession request already reviewed: {status}")


def normalize_profession_name(name: str) -> str:
    """Схлопывает пробелы: «Кинолог » и «Кинолог» — одна и та же профессия."""
    return " ".join((name or "").split())


def find_existing_category(name: str):
    """Ищет профессию в справочнике без учёта регистра, включая подкатегории."""
    from ..models import ProfessionCategory

    normalized = normalize_profession_name(name)
    if not normalized:
        return None
    return ProfessionCategory.objects.filter(name__iexact=normalized).order_by('parent_id', 'id').first()


def find_pending_duplicate(user, name: str):
    from ..models import ProfessionRequest

    return ProfessionRequest.objects.filter(
        user=user,
        status=ProfessionRequest.STATUS_PENDING,
        name__iexact=normalize_profession_name(name),
    ).first()


def create_profile_request(user, name: str, description: str):
    """Заявка из «Редактировать профиль». Дубли — 409, текст показывается пользователю как есть."""
    from ..models import ProfessionRequest

    name = normalize_profession_name(name)

    existing = find_existing_category(name)
    if existing:
        raise AppError(
            f"Профессия „{existing.name}“ уже есть в списке — выберите её",
            code=ErrorCode.CONFLICT,
            status_code=status.HTTP_409_CONFLICT,
            profession_category=existing.id,
        )

    if find_pending_duplicate(user, name):
        raise AppError(
            "Заявка на эту профессию уже на проверке",
            code=ErrorCode.CONFLICT,
            status_code=status.HTTP_409_CONFLICT,
        )

    request = ProfessionRequest.objects.create(
        user=user,
        name=name,
        description=description.strip(),
        source=ProfessionRequest.SOURCE_PROFILE,
    )
    _notify_admins(request)
    return request


def create_application_request(application):
    """Заявка из анкеты: создаётся вместе с анкетой, без проверок на дубли —
    старые сборки шлют только название, и анкета не должна из-за этого падать."""
    from ..models import ProfessionRequest

    name = normalize_profession_name(application.custom_profession)
    if not name or application.user is None:
        return None

    request = ProfessionRequest.objects.create(
        user=application.user,
        name=name,
        description=(application.custom_profession_description or "").strip(),
        source=ProfessionRequest.SOURCE_APPLICATION,
        application=application,
    )
    # Уведомление в Telegram уходит вместе с карточкой анкеты — отдельное не шлём.
    return request


@transaction.atomic
def approve_profession_request(request, category=None, reviewed_by: str = ""):
    """Одобряет pending-заявку: создаёт (или берёт указанную) категорию и применяет её."""
    from ..models import ProfessionRequest

    category = category or request.profession_category
    request = _lock_pending(request)

    request.status = ProfessionRequest.STATUS_APPROVED
    request.reason = ''
    request.profession_category = category
    request.reviewed_at = timezone.now()
    request.save(update_fields=['status', 'reason', 'profession_category', 'reviewed_at', 'updated_at'])

    apply_approval_effects(request, reviewed_by=reviewed_by)
    return request


@transaction.atomic
def reject_profession_request(request, reason: str, reviewed_by: str = ""):
    from ..models import ProfessionRequest

    request = _lock_pending(request)

    request.status = ProfessionRequest.STATUS_REJECTED
    request.reason = reason or ''
    request.reviewed_at = timezone.now()
    request.save(update_fields=['status', 'reason', 'reviewed_at', 'updated_at'])

    apply_rejection_effects(request, reviewed_by=reviewed_by)
    return request


def apply_approval_effects(request, reviewed_by: str = ""):
    """Побочные эффекты одобрения. Статус заявки уже должен быть approved.

    - категория: указанная модератором → уже существующая с таким именем → новая;
    - заявка из анкеты: категория проставляется в анкету, а если анкета уже
      принята — сразу специалисту;
    - заявка из профиля: специалисту профессия ставится сразу, клиент выберет её
      сам в анкете.
    """
    from ..models import ROLE_SPECIALIST, ProfessionCategory

    category = request.profession_category or find_existing_category(request.name)
    if category is None:
        category = ProfessionCategory.objects.create(name=request.name)
        logger.info("Profession category %s created from request %s", category.id, request.id)

    if request.profession_category_id != category.id:
        request.profession_category = category
        request.save(update_fields=['profession_category', 'updated_at'])

    user = request.user
    application = request.application

    if application is not None:
        if application.profession_id is None:
            application.profession = category
            application.save(update_fields=['profession', 'updated_at'])
        if application.status == 'accepted' and user.profession_id is None:
            user.profession = category
            user.save(update_fields=['profession'])
    elif user.role == ROLE_SPECIALIST:
        user.profession = category
        user.save(update_fields=['profession'])

    logger.info("Profession request %s approved by %s", request.id, reviewed_by or "admin")
    transaction.on_commit(lambda: _safe_push(send_profession_request_approved_push, user, request))


def apply_rejection_effects(request, reviewed_by: str = ""):
    logger.info(
        "Profession request %s rejected by %s: %s",
        request.id, reviewed_by or "admin", request.reason,
    )
    transaction.on_commit(lambda: _safe_push(send_profession_request_rejected_push, request.user, request))


def _lock_pending(request):
    from ..models import ProfessionRequest

    locked = ProfessionRequest.objects.select_for_update().get(pk=request.pk)
    if locked.status != ProfessionRequest.STATUS_PENDING:
        raise ProfessionRequestAlreadyReviewed(locked.status)
    return locked


def _notify_admins(request):
    from common.telegram_notifier import notify_profession_request

    try:
        notify_profession_request(request)
    except Exception:
        logger.exception("Failed to send Telegram notification for profession request %s", request.id)


def _safe_push(push_func, user, request):
    try:
        push_func(user, request)
    except Exception:
        logger.exception("Failed to send push for profession request %s", request.id)
