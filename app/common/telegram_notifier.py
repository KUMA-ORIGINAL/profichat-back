import logging
import time

import requests
from django.conf import settings
from django.utils import timezone

logger = logging.getLogger(__name__)

MAX_RETRIES = 3
BACKOFF_BASE = 1.5
TIMEOUT = 10


def send_telegram_notification(message: str) -> bool:
    bot_token = getattr(settings, 'TELEGRAM_BOT_TOKEN', None)
    chat_id = getattr(settings, 'TELEGRAM_CHAT_ID', None)
    thread_id = getattr(settings, 'TELEGRAM_THREAD_ID', None)

    if not bot_token or not chat_id:
        logger.warning("Telegram bot token or chat ID not configured. Skipping notification.")
        return False

    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"

    payload = {
        'chat_id': chat_id,
        'text': message,
        'parse_mode': 'HTML',
    }
    if thread_id:
        payload['message_thread_id'] = thread_id

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = requests.post(url, json=payload, timeout=TIMEOUT)

            if response.status_code == 429:
                retry_after = int(response.json().get('parameters', {}).get('retry_after', 2))
                logger.warning("Telegram rate-limited, retry after %ds (attempt %d/%d)", retry_after, attempt, MAX_RETRIES)
                time.sleep(retry_after)
                continue

            response.raise_for_status()
            logger.info("Telegram notification sent (attempt %d): %s…", attempt, message[:50])
            return True

        except requests.exceptions.RequestException as e:
            logger.error("Telegram send failed (attempt %d/%d): %s", attempt, MAX_RETRIES, e)
            if attempt < MAX_RETRIES:
                time.sleep(BACKOFF_BASE ** attempt)

    logger.error("Telegram notification failed after %d attempts: %s…", MAX_RETRIES, message[:80])
    return False


def notify_new_client_registration(user) -> bool:
    """
    Отправляет уведомление о регистрации нового клиента.
    
    Args:
        user: Объект пользователя
        
    Returns:
        bool: True если уведомление отправлено успешно
    """
    # Конвертируем время в локальный часовой пояс
    local_time = timezone.localtime(user.date_joined)
    
    message = (
        f"🆕 <b>Новый клиент зарегистрирован!</b>\n\n"
        f"👤 Имя: {user.first_name or 'Не указано'} {user.last_name or ''}\n"
        f"📱 Телефон: {user.phone_number or 'Не указан'}\n"
        f"🆔 ID: {user.id}\n"
        f"📅 Дата регистрации: {local_time.strftime('%d.%m.%Y %H:%M')}"
    )
    
    return send_telegram_notification(message)


def notify_specialist_application(application) -> bool:
    """
    Отправляет уведомление о новой заявке на специалиста.
    
    Args:
        application: Объект заявки
        
    Returns:
        bool: True если уведомление отправлено успешно
    """
    work_experiences = application.work_experiences.all()
    work_exp_text = "\n".join([f"  • {exp.name}" for exp in work_experiences]) if work_experiences else "  Не указан"
    
    # Конвертируем время в локальный часовой пояс
    local_time = timezone.localtime(application.created_at)
    
    message = (
        f"📋 <b>Новая заявка на специалиста!</b>\n\n"
        f"👤 ФИО: {application.last_name} {application.first_name}\n"
        f"🎓 Образование: {application.education}\n"
        f"💼 Профессия: {application.profession.name if application.profession else 'Не указана'}\n"
        f"📝 Опыт работы:\n{work_exp_text}\n"
        f"🆔 ID заявки: {application.id}\n"
        f"👤 Пользователь ID: {application.user.id if application.user else 'Не указан'}\n"
        f"📅 Дата подачи: {local_time.strftime('%d.%m.%Y %H:%M')}"
    )
    
    return send_telegram_notification(message)
