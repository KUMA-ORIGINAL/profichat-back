import logging

from django.utils import timezone
from firebase_admin import messaging
from push_notifications.models import GCMDevice

logger = logging.getLogger(__name__)

# firebase_admin отдаёт у этих ошибок обобщённые коды (NOT_FOUND, PERMISSION_DENIED),
# по которым непонятно, что случилось, — приводим к кодам FCM.
FCM_ERROR_CODES = {
    "UnregisteredError": "UNREGISTERED",
    "SenderIdMismatchError": "SENDER_ID_MISMATCH",
    "QuotaExceededError": "QUOTA_EXCEEDED",
    "ThirdPartyAuthError": "THIRD_PARTY_AUTH_ERROR",
    "InvalidArgumentError": "INVALID_ARGUMENT",
    "UnavailableError": "UNAVAILABLE",
    "InternalError": "INTERNAL",
}


def _safe_user_ref(user):
    return getattr(user, "id", None) or "unknown"


def _error_code(exc):
    name = exc.__class__.__name__
    return FCM_ERROR_CODES.get(name) or getattr(exc, "code", "") or name


def _record_device_result(device, ok, error_code="", error_message=""):
    """Сохраняет результат последней попытки доставки на устройство."""
    from account.models import PushDeviceStatus

    now = timezone.now()
    defaults = {"last_success_at": now} if ok else {
        "last_failure_at": now,
        "last_error_code": error_code,
        "last_error_message": error_message[:2000],
    }
    # push_notifications сам решает, мёртв ли токен, и снимает active —
    # перечитываем флаг из БД, чтобы не расходиться с ним.
    if not ok and device.pk and not GCMDevice.objects.filter(pk=device.pk, active=True).exists():
        defaults["deactivated_at"] = now

    try:
        PushDeviceStatus.objects.update_or_create(device=device, defaults=defaults)
    except Exception:
        logger.exception("Failed to store push status for device_id=%s", getattr(device, "id", None))


def _read_batch_response(response):
    """Разбирает BatchResponse от FCM.

    send_each() не бросает исключение при отказе по токену — ошибка приходит
    внутри ответа, поэтому без разбора отклонённая отправка выглядела успешной.
    """
    if response is None:
        return False, "NO_RESPONSE", "FCM не вернул ответ (устройство не FCM?)"

    if getattr(response, "success_count", 0) > 0:
        return True, "", ""

    exc = None
    for item in getattr(response, "responses", []) or []:
        if not item.success and item.exception is not None:
            exc = item.exception
            break

    if exc is None:
        return False, "UNKNOWN", "FCM отклонил отправку без описания ошибки"
    return False, _error_code(exc), str(exc)


def send_push(user, title, message, extra=None, log_prefix="[Push]", return_meta=False):
    """Простая отправка push-уведомления для Android и iOS"""
    devices = list(GCMDevice.objects.filter(user=user, active=True))
    device_count = len(devices)

    if not device_count:
        logger.info("%s No active devices for user_id=%s", log_prefix, _safe_user_ref(user))
        if return_meta:
            return {
                "ok": False,
                "success_count": 0,
                "device_count": 0,
                "error_code": "NO_DEVICES",
                "error_message": "Нет активных устройств",
            }
        return False

    success_count = 0
    error_codes = []
    error_messages = []

    for device in devices:
        try:
            logger.info(
                "%s Sending push to user_id=%s device_id=%s",
                log_prefix,
                _safe_user_ref(user),
                getattr(device, "id", None),
            )

            firebase_message = messaging.Message(
                data={k: str(v) for k, v in (extra or {}).items()},
                notification=messaging.Notification(
                    title=title,
                    body=message,
                ),
                token=device.registration_id,
                android=messaging.AndroidConfig(
                    priority="high",
                    notification=messaging.AndroidNotification(
                        sound="default",
                    ),
                ),
                apns=messaging.APNSConfig(
                    headers={
                        "apns-priority": "10",
                    },
                    payload=messaging.APNSPayload(
                        aps=messaging.Aps(
                            alert=messaging.ApsAlert(
                                title=title,
                                body=message,
                            ),
                            badge=1,
                            sound="default",
                        )
                    ),
                ),
            )

            response = device.send_message(firebase_message)
            ok, error_code, error_message = _read_batch_response(response)

            if ok:
                success_count += 1
                _record_device_result(device, ok=True)
                continue

            logger.warning(
                "%s Push rejected by FCM for user_id=%s device_id=%s code=%s: %s",
                log_prefix,
                _safe_user_ref(user),
                getattr(device, "id", None),
                error_code,
                error_message,
            )
            error_codes.append(error_code)
            error_messages.append(f"{error_code}: {error_message}")
            _record_device_result(device, ok=False, error_code=error_code, error_message=error_message)

        except Exception as e:
            logger.exception(
                "%s Push send failed for user_id=%s device_id=%s",
                log_prefix,
                _safe_user_ref(user),
                getattr(device, "id", None),
            )
            error_codes.append("EXCEPTION")
            error_messages.append(str(e))
            _record_device_result(device, ok=False, error_code="EXCEPTION", error_message=str(e))
            continue

    result = success_count > 0
    if return_meta:
        return {
            "ok": result,
            "success_count": success_count,
            "device_count": device_count,
            "error_code": error_codes[0] if error_codes else "",
            "error_message": "; ".join(error_messages),
        }
    return result


def create_notification(user, title, message, notification_type, payload=None):
    from account.models import Notification

    return Notification.objects.create(
        recipient=user,
        notification_type=notification_type,
        title=title,
        message=message,
        payload=payload or {},
    )


def notify_user(
    user,
    title,
    message,
    notification_type,
    payload=None,
    log_prefix="[Notify]",
    return_meta=False,
):
    notification = create_notification(
        user=user,
        title=title,
        message=message,
        notification_type=notification_type,
        payload=payload,
    )

    push_result = send_push(
        user=user,
        title=title,
        message=message,
        extra=payload or {},
        log_prefix=log_prefix,
        return_meta=True,
    )
    if push_result.get("ok"):
        notification.pushed_at = timezone.now()
        notification.save(update_fields=["pushed_at", "updated_at"])

    if return_meta:
        push_result["notification_id"] = notification.id
        return push_result
    return push_result.get("ok", False)


def send_payment_success_push(user, access_order):
    title = "Оплата прошла успешно"
    message = f"Доступ по тарифу '{access_order.tariff.name}' активирован."
    extra = {"order_id": str(access_order.id)}
    return notify_user(
        user=user,
        title=title,
        message=message,
        notification_type="payment_success",
        payload=extra,
        log_prefix="[Push][Payment]",
    )


def send_chat_invite_push(user, chat, return_meta=False):
    title = "Новый чат"
    message = "Вас пригласили в чат со специалистом"
    extra = {
        "chat_id": str(chat.id),
        "type": "chat_invite",
        "channel_id": str(chat.channel_id),
        "sender_name": str(user.get_full_name()),
        "sender_id": str(user.id),
    }
    return notify_user(
        user=user,
        title=title,
        message=message,
        notification_type="chat_invite",
        payload=extra,
        log_prefix="[Push][Chat]",
        return_meta=return_meta,
    )


def send_application_accepted_push(user, application):
    title = "Ваша заявка одобрена!"
    message = "Поздравляем, теперь вы специалист на платформе."
    extra = {
        "application_id": str(application.id),
        "type": "application_accepted",
    }
    return notify_user(
        user=user,
        title=title,
        message=message,
        notification_type="application_accepted",
        payload=extra,
        log_prefix="[Push][Application]",
    )


def send_application_rejected_push(user, application):
    title = "Заявка отклонена"
    reason = (application.rejection_reason or "").strip()
    message = f"Причина: {reason}" if reason else "К сожалению, ваша заявка отклонена."
    extra = {
        "application_id": str(application.id),
        "type": "application_rejected",
        "rejection_reason": reason,
    }
    return notify_user(
        user=user,
        title=title,
        message=message,
        notification_type="application_rejected",
        payload=extra,
        log_prefix="[Push][Application]",
    )
