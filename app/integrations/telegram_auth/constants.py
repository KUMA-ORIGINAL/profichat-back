STATUS_PENDING = "pending"
STATUS_WAITING_CONTACT = "waiting_contact"
STATUS_COMPLETED = "completed"

TELEGRAM_AUTH_STATUSES = (
    (STATUS_PENDING, "Сессия создана, пользователь еще не перешел в бота."),
    (STATUS_WAITING_CONTACT, "Пользователь перешел в бота, ожидается отправка контакта."),
    (STATUS_COMPLETED, "Контакт подтвержден, токены доступны для входа."),
)

SESSION_ID_TOKEN_BYTES = 24
DEFAULT_SESSION_TTL_SECONDS = 300
CONSUMED_SESSION_TTL_SECONDS = 30
TELEGRAM_SEND_TIMEOUT_SECONDS = 10

SESSION_CACHE_KEY_PREFIX = "telegram_auth:session"
CHAT_CACHE_KEY_PREFIX = "telegram_auth:chat"

MESSAGE_CONTACT_REQUEST = "Для авторизации отправьте, пожалуйста, ваш контакт."
MESSAGE_EXPIRED_SESSION = "Сессия авторизации не найдена или истекла. Вернитесь в приложение и попробуйте снова."
MESSAGE_NOT_OWN_CONTACT = "Пожалуйста, отправьте именно свой контакт."
MESSAGE_INACTIVE_SESSION = "Сессия авторизации не активна. Нажмите вход через Telegram в приложении снова."
MESSAGE_AUTH_CONFIRMED = "Контакт получен. Авторизация подтверждена."
MESSAGE_INVALID_WEBHOOK_SECRET = "Invalid webhook secret."
MESSAGE_SESSION_NOT_FOUND = "Сессия не найдена или истекла."
MESSAGE_SESSION_ALREADY_USED = "Сессия уже использована."

TELEGRAM_CONTACT_BUTTON_TEXT = "Отправить контакт"
