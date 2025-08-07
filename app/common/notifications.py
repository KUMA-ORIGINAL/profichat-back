import logging
from firebase_admin import messaging
from push_notifications.models import GCMDevice

logger = logging.getLogger(__name__)


def send_push(user, title, message, extra=None, log_prefix="[Push]"):
    """Простая отправка push-уведомления для Android и iOS"""
    devices = GCMDevice.objects.filter(user=user, active=True)

    if not devices.exists():
        logger.info(f"{log_prefix} Нет активных устройств для пользователя {user}")
        return False

    success_count = 0

    for device in devices:
        try:
            logger.info(f"{log_prefix} Отправка push пользователю {user}: {message}")

            # Создаем простое сообщение
            firebase_message = messaging.Message(
                # Данные
                data={k: str(v) for k, v in (extra or {}).items()},

                # Уведомление
                notification=messaging.Notification(
                    title=title,
                    body=message
                ),

                # Токен
                token=device.registration_id,

                # Настройки для Android
                android=messaging.AndroidConfig(
                    priority='high',
                    notification=messaging.AndroidNotification(
                        sound="default"
                    )
                ),

                # Настройки для iOS
                apns=messaging.APNSConfig(
                    headers={
                        'apns-priority': '10'
                    },
                    payload=messaging.APNSPayload(
                        aps=messaging.Aps(
                            alert=messaging.ApsAlert(
                                title=title,
                                body=message
                            ),
                            badge=1,
                            sound='default'
                        )
                    )
                )
            )

            # Отправляем
            device.send_message(firebase_message)
            success_count += 1

        except Exception as e:
            logger.error(f"{log_prefix} Ошибка отправки push: {e}")
            continue

    return success_count > 0


def send_payment_success_push(user, access_order):
    title = "Оплата прошла успешно"
    message = f"Доступ по тарифу '{access_order.tariff.name}' активирован."
    extra = {"order_id": str(access_order.id)}
    return send_push(user, title, message, extra, log_prefix="[Push][Payment]")


def send_chat_invite_push(user, chat):
    title = "Новый чат"
    message = "Вас пригласили в чат со специалистом"
    extra = {
        "chat_id": str(chat.id),
        "type": "chat_invite",
        "channel_id": str(chat.channel_id),
        "sender_name": str(user.get_full_name()),  # или другое поле имени отправителя
        "sender_id": str(user.id)
    }
    return send_push(user, title, message, extra, log_prefix="[Push][Chat]")


def send_application_accepted_push(user, application):
    title = "Ваша заявка одобрена!"
    message = "Поздравляем, теперь вы специалист на платформе."
    extra = {
        "application_id": str(application.id),
        "type": "application_accepted"
    }
    return send_push(user, title, message, extra, log_prefix="[Push][Application]")
