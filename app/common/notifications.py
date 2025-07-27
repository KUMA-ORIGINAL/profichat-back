import logging
from push_notifications.models import GCMDevice   # оставлено только для хранения токенов
from firebase_admin import messaging

from config.settings import firebase_app

logger = logging.getLogger(__name__)

# ---------------------------------------------------------
# Внутренняя функция отправки ОДНОГО сообщения
# ---------------------------------------------------------
def _send_single(token: str, title: str, body: str, extra: dict | None = None) -> bool:
    """
    Отправляет одно сообщение через Firebase Admin SDK.
    Возвращает True, если сообщение было успешно доставлено.
    """
    message = messaging.Message(
        notification=messaging.Notification(
            title=title,
            body=body,
        ),
        android=messaging.AndroidConfig(
            priority="high",
            notification=messaging.AndroidNotification(
                sound="default",
                default_vibrate_timings=True,
            ),
        ),
        apns=messaging.APNSConfig(
            payload=messaging.APNSPayload(
                aps=messaging.Aps(
                    alert=messaging.ApsAlert(title=title, body=body),
                    sound="default",
                    badge=1,
                    content_available=True,
                ),
            ),
        ),
        data={str(k): str(v) for k, v in (extra or {}).items()},
        token=token,
    )

    try:
        messaging.send(message, app=firebase_app)
        return True
    except Exception as e:
        logger.error(f"[Push] Ошибка при отправке на токен {token[-8:]}: {e}")
        return False


# ---------------------------------------------------------
# Публичная функция отправки пользователю
# ---------------------------------------------------------
def send_push(user, title, message, extra=None, log_prefix="[Push]") -> bool:
    """
    Отправляет push-уведомление всем активным устройствам пользователя.
    Возвращает True, если хотя бы одно сообщение было успешно доставлено.
    """
    devices = GCMDevice.objects.filter(user=user, active=True)
    if not devices.exists():
        logger.info(f"{log_prefix} Нет активных устройств для пользователя {user}")
        return False

    success = 0
    for device in devices:
        ok = _send_single(device.registration_id, title, message, extra)
        success += int(ok)

    if success:
        logger.info(f"{log_prefix} Успешно отправлено {success}/{len(devices)} сообщений")
    return success > 0


# ---------------------------------------------------------
# Удобные обёртки
# ---------------------------------------------------------
def send_payment_success_push(user, access_order):
    send_push(
        user,
        title="Оплата прошла успешно",
        message=f"Доступ по тарифу '{access_order.tariff.name}' активирован.",
        extra={"order_id": str(access_order.id)},
        log_prefix="[Push][Payment]",
    )

def send_chat_invite_push(user, chat):
    send_push(
        user,
        title="Новый чат",
        message="Вас пригласили в чат со специалистом",
        extra={"chat_id": str(chat.id), "type": "chat_invite"},
        log_prefix="[Push][Chat]",
    )

def send_application_accepted_push(user, application):
    send_push(
        user,
        title="Ваша заявка одобрена!",
        message="Поздравляем, теперь вы специалист на платформе.",
        extra={"application_id": str(application.id), "type": "application_accepted"},
        log_prefix="[Push][Application]",
    )
