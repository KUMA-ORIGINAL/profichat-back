"""Обработка нажатий на инлайн-кнопки в админском Telegram-чате.

Логика вынесена из вьюхи, потому что уведомления и авторизация могут работать
на одном и том же боте — тогда апдейты приходят на webhook авторизации, и он
делегирует их сюда.
"""

import logging

from django.conf import settings
from django.core.cache import cache
from django.utils import timezone

from common.telegram_notifier import (
    CALLBACK_APPROVE,
    CALLBACK_BACK,
    CALLBACK_CUSTOM_REASON,
    CALLBACK_REJECT,
    CALLBACK_REJECT_REASON,
    REJECTION_REASONS,
    answer_callback_query,
    application_review_keyboard,
    build_application_message,
    edit_message_text,
    rejection_reasons_keyboard,
    send_telegram_notification,
    telegram_api_call,
)

logger = logging.getLogger(__name__)

CUSTOM_REASON_CACHE_PREFIX = "telegram_admin:custom_reason"
CUSTOM_REASON_TTL_SECONDS = 15 * 60
CUSTOM_REASON_PROMPT = "Отправьте ответом на это сообщение причину отказа по заявке #{application_id}."

MESSAGE_NOT_ALLOWED = "Нет прав на рассмотрение заявок."
MESSAGE_NOT_FOUND = "Заявка не найдена."
MESSAGE_ALREADY_REVIEWED = "Заявка уже рассмотрена: {status}."
MESSAGE_APPROVED = "Заявка одобрена."
MESSAGE_REJECTED = "Заявка отклонена."

STATUS_LABELS = {
    'pending': 'На рассмотрении',
    'accepted': 'Принято',
    'rejected': 'Отклонено',
}

ADMIN_CALLBACK_PREFIXES = (
    CALLBACK_APPROVE,
    CALLBACK_REJECT,
    CALLBACK_REJECT_REASON,
    CALLBACK_BACK,
    CALLBACK_CUSTOM_REASON,
)


def _custom_reason_cache_key(chat_id, message_id):
    return f"{CUSTOM_REASON_CACHE_PREFIX}:{chat_id}:{message_id}"


def _reviewer_label(from_user):
    username = from_user.get("username")
    if username:
        return f"@{username}"
    name = " ".join(filter(None, [from_user.get("first_name"), from_user.get("last_name")]))
    return name or f"tg:{from_user.get('id')}"


def _is_allowed(chat_id, from_user) -> bool:
    """Решать по заявкам может любой участник рабочего чата — важен только сам чат."""
    expected_chat_id = str(getattr(settings, "TELEGRAM_CHAT_ID", "") or "")
    if expected_chat_id and str(chat_id) != expected_chat_id:
        logger.warning(
            "Telegram admin callback from unexpected chat_id=%s user_id=%s",
            chat_id, from_user.get("id"),
        )
        return False

    return True


def _get_application(application_id):
    from account.models import Application

    return Application.objects.filter(pk=application_id).first()


def _decision_footer(application, reviewer, decision_text):
    local_time = timezone.localtime(timezone.now())
    lines = [f"{decision_text} — {reviewer}, {local_time.strftime('%d.%m.%Y %H:%M')}"]
    if application.rejection_reason:
        lines.append(f"Причина: {application.rejection_reason}")
    return "\n".join(lines)


def _refresh_card(application, chat_id, message_id, reviewer, decision_text, keyboard=None):
    text = build_application_message(application, footer=_decision_footer(application, reviewer, decision_text))
    edit_message_text(chat_id, message_id, text, reply_markup=keyboard)


def is_admin_update(update: dict) -> bool:
    """True, если апдейт относится к рассмотрению заявок (кнопки или ответ с причиной)."""
    callback_query = update.get("callback_query")
    if callback_query:
        data = (callback_query.get("data") or "")
        return data.split(":", 1)[0] in ADMIN_CALLBACK_PREFIXES

    message = update.get("message") or {}
    reply_to = message.get("reply_to_message") or {}
    if not reply_to:
        return False
    chat_id = (message.get("chat") or {}).get("id")
    return cache.get(_custom_reason_cache_key(chat_id, reply_to.get("message_id"))) is not None


def handle_admin_update(update: dict) -> bool:
    """Обрабатывает апдейт. Возвращает True, если апдейт был «наш»."""
    callback_query = update.get("callback_query")
    if callback_query:
        return _handle_callback_query(callback_query)

    message = update.get("message")
    if message:
        return _handle_custom_reason_reply(message)

    return False


def _handle_callback_query(callback_query: dict) -> bool:
    data = callback_query.get("data") or ""
    action, _, rest = data.partition(":")
    if action not in ADMIN_CALLBACK_PREFIXES:
        return False

    callback_id = callback_query.get("id")
    from_user = callback_query.get("from") or {}
    message = callback_query.get("message") or {}
    chat_id = (message.get("chat") or {}).get("id")
    message_id = message.get("message_id")

    if not _is_allowed(chat_id, from_user):
        answer_callback_query(callback_id, MESSAGE_NOT_ALLOWED, show_alert=True)
        return True

    parts = rest.split(":")
    application_id = parts[0] if parts else ""
    application = _get_application(application_id)
    if application is None:
        answer_callback_query(callback_id, MESSAGE_NOT_FOUND, show_alert=True)
        return True

    reviewer = _reviewer_label(from_user)

    if action == CALLBACK_REJECT:
        answer_callback_query(callback_id)
        _refresh_card(
            application, chat_id, message_id, reviewer,
            "Выберите причину отказа:",
            keyboard=rejection_reasons_keyboard(application.id),
        )
        return True

    if action == CALLBACK_BACK:
        answer_callback_query(callback_id)
        edit_message_text(
            chat_id, message_id,
            build_application_message(application),
            reply_markup=application_review_keyboard(application.id),
        )
        return True

    if action == CALLBACK_CUSTOM_REASON:
        answer_callback_query(callback_id)
        _request_custom_reason(application, chat_id, message)
        return True

    if action == CALLBACK_APPROVE:
        _apply_decision(
            application=application,
            approve=True,
            reason="",
            reviewer=reviewer,
            chat_id=chat_id,
            message_id=message_id,
            callback_id=callback_id,
        )
        return True

    if action == CALLBACK_REJECT_REASON:
        try:
            reason = REJECTION_REASONS[int(parts[1])]
        except (IndexError, ValueError):
            answer_callback_query(callback_id, "Причина не распознана.", show_alert=True)
            return True
        _apply_decision(
            application=application,
            approve=False,
            reason=reason,
            reviewer=reviewer,
            chat_id=chat_id,
            message_id=message_id,
            callback_id=callback_id,
        )
        return True

    return False


def _apply_decision(application, approve, reason, reviewer, chat_id, message_id, callback_id=None):
    from account.services.application_review import (
        ApplicationAlreadyReviewed,
        approve_application,
        reject_application,
    )

    try:
        if approve:
            approve_application(application, reviewed_by=reviewer)
        else:
            reject_application(application, reason=reason, reviewed_by=reviewer)
    except ApplicationAlreadyReviewed as exc:
        text = MESSAGE_ALREADY_REVIEWED.format(status=STATUS_LABELS.get(exc.status, exc.status))
        if callback_id:
            answer_callback_query(callback_id, text, show_alert=True)
        else:
            send_telegram_notification(f"⚠️ {text} (заявка #{application.id})")
        application.refresh_from_db()
        _refresh_card(application, chat_id, message_id, reviewer, "Решение уже принято", keyboard=None)
        return

    application.refresh_from_db()
    decision_text = "✅ Одобрено" if approve else "❌ Отклонено"
    if callback_id:
        answer_callback_query(callback_id, MESSAGE_APPROVED if approve else MESSAGE_REJECTED)
    _refresh_card(application, chat_id, message_id, reviewer, decision_text, keyboard=None)


def _request_custom_reason(application, chat_id, message):
    payload = {
        'chat_id': chat_id,
        'text': CUSTOM_REASON_PROMPT.format(application_id=application.id),
        'reply_markup': {'force_reply': True, 'selective': True},
    }
    thread_id = message.get("message_thread_id")
    if thread_id:
        payload['message_thread_id'] = thread_id

    result = telegram_api_call('sendMessage', payload)
    if not result:
        return

    cache.set(
        _custom_reason_cache_key(chat_id, result.get("message_id")),
        {"application_id": application.id, "card_message_id": message.get("message_id")},
        timeout=CUSTOM_REASON_TTL_SECONDS,
    )


def _handle_custom_reason_reply(message: dict) -> bool:
    reply_to = message.get("reply_to_message") or {}
    if not reply_to:
        return False

    chat_id = (message.get("chat") or {}).get("id")
    cache_key = _custom_reason_cache_key(chat_id, reply_to.get("message_id"))
    pending = cache.get(cache_key)
    if not pending:
        return False

    from_user = message.get("from") or {}
    if not _is_allowed(chat_id, from_user):
        return True

    reason = (message.get("text") or "").strip()
    if not reason:
        return True

    application = _get_application(pending["application_id"])
    if application is None:
        cache.delete(cache_key)
        send_telegram_notification(f"⚠️ {MESSAGE_NOT_FOUND} (#{pending['application_id']})")
        return True

    cache.delete(cache_key)
    _apply_decision(
        application=application,
        approve=False,
        reason=reason,
        reviewer=_reviewer_label(from_user),
        chat_id=chat_id,
        message_id=pending["card_message_id"],
    )
    return True
