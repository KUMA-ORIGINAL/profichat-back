import logging

from push_notifications.models import GCMDevice

logger = logging.getLogger(__name__)


def send_payment_success_push(user, access_order):
    device = GCMDevice.objects.filter(user=user, active=True).first()
    if not device:
        logger.info(f"Нет активных устройств для пользователя {user}")
        return

    title = "Оплата прошла успешно"
    message = f"Доступ по тарифу '{access_order.tariff.name}' активирован."

    logger.info(f"Отправка push пользователю {user}: {message}")

    device.send_message(
        message,
        title=title,
        extra={"order_id": str(access_order.id)}
    )


def send_chat_invite_push(user, chat):
    device = GCMDevice.objects.filter(user=user, active=True).first()
    if not device:
        logger.info(f"[Push] Нет активных устройств для пользователя {user}")
        return

    title = "Новый чат"
    message = f"Вас пригласили в чат со специалистом"

    logger.info(f"[Push] Отправка приглашения в чат пользователю {user}: {message}")

    device.send_message(
        message,
        title=title,
        extra={
            "chat_id": str(chat.id),
            "type": "chat_invite"
        }
    )
