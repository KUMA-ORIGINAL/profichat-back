import logging
import time

import requests
from django.conf import settings
from django.utils import timezone

logger = logging.getLogger(__name__)

MAX_RETRIES = 3
BACKOFF_BASE = 1.5
TIMEOUT = 10

TELEGRAM_MESSAGE_LIMIT = 4096

CALLBACK_APPROVE = "app_approve"
CALLBACK_REJECT = "app_reject"
CALLBACK_REJECT_REASON = "app_reason"
CALLBACK_BACK = "app_back"
CALLBACK_CUSTOM_REASON = "app_custom"

# Готовые причины отказа: индекс попадает в callback_data, поэтому порядок менять нельзя —
# у старых сообщений в чате остаются кнопки со старыми индексами.
REJECTION_REASONS = [
    "Недостаточно данных в заявке",
    "Не подтверждена квалификация",
    "Дубликат заявки",
    "Не соответствует профилю платформы",
]


def _bot_token():
    return getattr(settings, 'TELEGRAM_BOT_TOKEN', None)


def telegram_api_call(method: str, payload: dict, bot_token: str = None) -> dict:
    """Вызывает метод Bot API с ретраями. Возвращает result или None."""
    bot_token = bot_token or _bot_token()
    if not bot_token:
        logger.warning("Telegram bot token not configured. Skipping %s.", method)
        return None

    url = f"https://api.telegram.org/bot{bot_token}/{method}"

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = requests.post(url, json=payload, timeout=TIMEOUT)

            if response.status_code == 429:
                retry_after = int(response.json().get('parameters', {}).get('retry_after', 2))
                logger.warning("Telegram rate-limited, retry after %ds (attempt %d/%d)", retry_after, attempt, MAX_RETRIES)
                time.sleep(retry_after)
                continue

            response.raise_for_status()
            logger.info("Telegram %s ok (attempt %d)", method, attempt)
            return response.json().get('result')

        except requests.exceptions.RequestException as e:
            body = getattr(getattr(e, 'response', None), 'text', '')
            logger.error("Telegram %s failed (attempt %d/%d): %s %s", method, attempt, MAX_RETRIES, e, body)
            if attempt < MAX_RETRIES:
                time.sleep(BACKOFF_BASE ** attempt)

    logger.error("Telegram %s failed after %d attempts", method, MAX_RETRIES)
    return None


def send_telegram_notification(
    message: str,
    reply_markup: dict = None,
    chat_id=None,
    thread_id=None,
    parse_mode: str = 'HTML',
) -> bool:
    chat_id = chat_id if chat_id is not None else getattr(settings, 'TELEGRAM_CHAT_ID', None)
    if thread_id is None:
        thread_id = getattr(settings, 'TELEGRAM_THREAD_ID', None)

    if not chat_id:
        logger.warning("Telegram chat ID not configured. Skipping notification.")
        return False

    payload = {
        'chat_id': chat_id,
        'text': message[:TELEGRAM_MESSAGE_LIMIT],
    }
    if parse_mode:
        payload['parse_mode'] = parse_mode
    if thread_id:
        payload['message_thread_id'] = thread_id
    if reply_markup:
        payload['reply_markup'] = reply_markup

    return telegram_api_call('sendMessage', payload) is not None


def answer_callback_query(callback_query_id: str, text: str = "", show_alert: bool = False) -> bool:
    payload = {'callback_query_id': callback_query_id, 'show_alert': show_alert}
    if text:
        payload['text'] = text[:200]
    return telegram_api_call('answerCallbackQuery', payload) is not None


def edit_message_text(chat_id, message_id, text: str, reply_markup: dict = None) -> bool:
    payload = {
        'chat_id': chat_id,
        'message_id': message_id,
        'text': text[:TELEGRAM_MESSAGE_LIMIT],
        'parse_mode': 'HTML',
    }
    payload['reply_markup'] = reply_markup or {'inline_keyboard': []}
    return telegram_api_call('editMessageText', payload) is not None


def edit_message_reply_markup(chat_id, message_id, reply_markup: dict = None) -> bool:
    payload = {
        'chat_id': chat_id,
        'message_id': message_id,
        'reply_markup': reply_markup or {'inline_keyboard': []},
    }
    return telegram_api_call('editMessageReplyMarkup', payload) is not None


def application_review_keyboard(application_id) -> dict:
    return {
        'inline_keyboard': [[
            {'text': '✅ Одобрить', 'callback_data': f'{CALLBACK_APPROVE}:{application_id}'},
            {'text': '❌ Отклонить', 'callback_data': f'{CALLBACK_REJECT}:{application_id}'},
        ]]
    }


def rejection_reasons_keyboard(application_id) -> dict:
    rows = [
        [{'text': reason, 'callback_data': f'{CALLBACK_REJECT_REASON}:{application_id}:{index}'}]
        for index, reason in enumerate(REJECTION_REASONS)
    ]
    rows.append([{'text': '✏️ Своя причина', 'callback_data': f'{CALLBACK_CUSTOM_REASON}:{application_id}'}])
    rows.append([{'text': '⬅️ Назад', 'callback_data': f'{CALLBACK_BACK}:{application_id}'}])
    return {'inline_keyboard': rows}


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


def build_application_message(application, footer: str = "") -> str:
    """Собирает текст карточки заявки (используется и при отправке, и при правке сообщения)."""
    work_experiences = application.work_experiences.all()
    work_exp_text = "\n".join([f"  • {exp.name}" for exp in work_experiences]) if work_experiences else "  Не указан"

    # Конвертируем время в локальный часовой пояс
    local_time = timezone.localtime(application.created_at)

    profession_text = application.profession.name if application.profession else (application.custom_profession or 'Не указана')
    organization_text = application.organization.name if application.organization else (application.custom_organization or 'Не указана')

    message = (
        f"📋 <b>Новая заявка на специалиста!</b>\n\n"
        f"👤 ФИО: {application.last_name} {application.first_name}\n"
        f"🎓 Образование: {application.education}\n"
        f"💼 Профессия: {profession_text}\n"
        f"🏢 Организация: {organization_text}\n"
        f"📝 Опыт работы:\n{work_exp_text}\n"
        f"🆔 ID заявки: {application.id}\n"
        f"👤 Пользователь ID: {application.user.id if application.user else 'Не указан'}\n"
        f"📅 Дата подачи: {local_time.strftime('%d.%m.%Y %H:%M')}"
    )
    if footer:
        message = f"{message}\n\n{footer}"
    return message


def notify_specialist_application(application) -> bool:
    """
    Отправляет уведомление о новой заявке на специалиста с кнопками решения.

    Args:
        application: Объект заявки

    Returns:
        bool: True если уведомление отправлено успешно
    """
    return send_telegram_notification(
        build_application_message(application),
        reply_markup=application_review_keyboard(application.id),
    )
