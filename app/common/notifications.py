import logging

from push_notifications.models import GCMDevice

logger = logging.getLogger(__name__)


def send_push(user, title, message, extra=None, log_prefix="[Push]"):
    device = GCMDevice.objects.filter(user=user, active=True).first()
    if not device:
        logger.info(f"{log_prefix} Нет активных устройств для пользователя {user}")
        return

    logger.info(f"{log_prefix} Отправка push пользователю {user}: {message}")

    device.send_message(
        message,
        title=title,
        extra=extra or {}
    )


def send_payment_success_push(user, access_order):
    title = "Оплата прошла успешно"
    message = f"Доступ по тарифу '{access_order.tariff.name}' активирован."
    extra = {"order_id": str(access_order.id)}
    send_push(user, title, message, extra, log_prefix="[Push][Payment]")


def send_chat_invite_push(user, chat):
    title = "Новый чат"
    message = "Вас пригласили в чат со специалистом"
    extra = {
        "chat_id": str(chat.id),
        "type": "chat_invite"
    }
    send_push(user, title, message, extra, log_prefix="[Push][Chat]")


def send_application_accepted_push(user, application):
    title = "Ваша заявка одобрена!"
    message = "Поздравляем, теперь вы специалист на платформе."
    extra = {
        "application_id": str(application.id),
        "type": "application_accepted"
    }
    send_push(user, title, message, extra, log_prefix="[Push][Application]")
