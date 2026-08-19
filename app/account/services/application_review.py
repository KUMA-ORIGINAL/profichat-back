import logging

from django.db import transaction

from common.notifications import send_application_accepted_push, send_application_rejected_push

logger = logging.getLogger(__name__)

STATUS_PENDING = 'pending'
STATUS_ACCEPTED = 'accepted'
STATUS_REJECTED = 'rejected'


class ApplicationAlreadyReviewed(Exception):
    """Заявку уже рассмотрели — повторное решение не применяется."""

    def __init__(self, status):
        self.status = status
        super().__init__(f"Application already reviewed: {status}")


@transaction.atomic
def approve_application(application, reviewed_by: str = ""):
    """Переводит pending-заявку в accepted и выполняет все побочные эффекты."""
    application = _lock_pending(application)

    application.status = STATUS_ACCEPTED
    application.rejection_reason = ''
    application.save(update_fields=['status', 'rejection_reason', 'updated_at'])

    apply_approval_effects(application, reviewed_by=reviewed_by)
    return application


@transaction.atomic
def reject_application(application, reason: str, reviewed_by: str = ""):
    """Переводит pending-заявку в rejected с причиной и уведомляет пользователя."""
    application = _lock_pending(application)

    application.status = STATUS_REJECTED
    application.rejection_reason = reason or ''
    application.save(update_fields=['status', 'rejection_reason', 'updated_at'])

    apply_rejection_effects(application, reviewed_by=reviewed_by)
    return application


def apply_approval_effects(application, reviewed_by: str = ""):
    """Выдаёт роль специалиста и шлёт пуш. Статус заявки уже должен быть accepted."""
    from ..models import ROLE_SPECIALIST

    user = application.user
    if user:
        user.role = ROLE_SPECIALIST
        user.profession = application.profession
        if application.organization:
            user.organization = application.organization
        user.save()

    logger.info("Application %s approved by %s", application.id, reviewed_by or "admin")

    if user:
        transaction.on_commit(lambda: _safe_push(send_application_accepted_push, user, application))


def apply_rejection_effects(application, reviewed_by: str = ""):
    """Шлёт пуш об отказе. Статус заявки уже должен быть rejected."""
    logger.info(
        "Application %s rejected by %s: %s",
        application.id, reviewed_by or "admin", application.rejection_reason,
    )

    user = application.user
    if user:
        transaction.on_commit(lambda: _safe_push(send_application_rejected_push, user, application))


def _lock_pending(application):
    """Перечитывает заявку под блокировкой: решение могли уже принять в другом месте."""
    locked = type(application).objects.select_for_update().get(pk=application.pk)
    if locked.status != STATUS_PENDING:
        raise ApplicationAlreadyReviewed(locked.status)
    return locked


def _safe_push(push_func, user, application):
    try:
        push_func(user, application)
    except Exception:
        logger.exception("Failed to send push for application %s", application.id)
