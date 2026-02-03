import logging
import requests
from django.conf import settings
from django.utils import timezone
from typing import Optional

logger = logging.getLogger(__name__)


def send_telegram_notification(message: str) -> bool:
    """
    Отправляет уведомление в Telegram.
    
    Args:
        message: Текст сообщения для отправки
        
    Returns:
        bool: True если сообщение отправлено успешно, False в противном случае
    """
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
        'parse_mode': 'HTML'
    }
    
    # Добавляем thread_id если он указан (для топиков/форумов)
    if thread_id:
        payload['message_thread_id'] = thread_id
    
    try:
        response = requests.post(url, json=payload, timeout=10)
        response.raise_for_status()
        logger.info(f"Telegram notification sent successfully: {message[:50]}...")
        return True
    except requests.exceptions.RequestException as e:
        logger.error(f"Failed to send Telegram notification: {str(e)}")
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
