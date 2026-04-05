import logging

from django.utils import timezone
from firebase_admin import messaging
from push_notifications.models import GCMDevice

logger = logging.getLogger(__name__)


def _safe_user_ref(user):
    return getattr(user, "id", None) or "unknown"


def send_push(user, title, message, extra=None, log_prefix="[Push]", return_meta=False):
    """Простая отправка push-уведомления для Android и iOS"""
    devices = GCMDevice.objects.filter(user=user, active=True)

    if not devices.exists():
        logger.info("%s No active devices for user_id=%s", log_prefix, _safe_user_ref(user))
        if return_meta:
            return {
                "ok": False,
                "success_count": 0,
                "device_count": 0,
                "error_message": "Нет активных устройств",
            }
        return False

    success_count = 0
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

            device.send_message(firebase_message)
            success_count += 1

        except Exception as e:
            logger.exception(
                "%s Push send failed for user_id=%s device_id=%s",
                log_prefix,
                _safe_user_ref(user),
                getattr(device, "id", None),
            )
            error_messages.append(str(e))
            continue

    result = success_count > 0
    if return_meta:
        return {
            "ok": result,
            "success_count": success_count,
            "device_count": devices.count(),
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

