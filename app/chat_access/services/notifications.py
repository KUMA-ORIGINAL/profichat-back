import logging

from push_notifications.models import GCMDevice

logger = logging.getLogger(__name__)


def send_payment_success_push(user, access_order):
    devices = GCMDevice.objects.filter(user=user, active=True)
    if not devices:
        logger.info(f"Нет активных устройств для пользователя {user}")
        return

    title = "Оплата прошла успешно"
    message = f"Доступ по тарифу '{access_order.tariff.name}' активирован."

    logger.info(f"Отправка push пользователю {user}: {message}")

    devices.send_message(
        message,
        title=title,
        extra={"order_id": access_order.id}
    )
