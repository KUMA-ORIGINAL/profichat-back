"""Отправка ошибок в Telegram — лёгкая замена/дополнение Sentry.

Подключается как logging-хендлер: любой log.error/exception и необработанное
исключение (django.request) уходит в отдельный чат/топик Telegram.
"""

import hashlib
import html
import logging
import threading
import time
import traceback
from concurrent.futures import ThreadPoolExecutor

from django.conf import settings

MAX_TRACEBACK_CHARS = 2500
MAX_MESSAGE_CHARS = 3500

# Логи самих отправок и HTTP-клиента — иначе ошибка отправки в Telegram
# порождает новую ошибку и так по кругу.
IGNORED_LOGGER_PREFIXES = (
    "common.telegram_logging",
    "common.telegram_notifier",
    "urllib3",
    "requests",
    "charset_normalizer",
)


class _Throttle:
    """Дедупликация одинаковых ошибок и общий лимит частоты (в пределах процесса)."""

    def __init__(self, dedupe_seconds, max_per_minute):
        self.dedupe_seconds = dedupe_seconds
        self.max_per_minute = max_per_minute
        self._lock = threading.Lock()
        self._seen = {}
        self._minute_start = 0.0
        self._minute_count = 0

    def check(self, fingerprint):
        """Возвращает (можно_слать, сколько_подавлено_с_прошлой_отправки)."""
        now = time.monotonic()
        with self._lock:
            if now - self._minute_start >= 60:
                self._minute_start = now
                self._minute_count = 0
            if self._minute_count >= self.max_per_minute:
                return False, 0

            last_sent, suppressed = self._seen.get(fingerprint, (0.0, 0))
            if last_sent and now - last_sent < self.dedupe_seconds:
                self._seen[fingerprint] = (last_sent, suppressed + 1)
                return False, 0

            self._seen[fingerprint] = (now, 0)
            self._minute_count += 1
            if len(self._seen) > 500:
                self._prune(now)
            return True, suppressed

    def _prune(self, now):
        stale = [key for key, (last, _) in self._seen.items() if now - last > self.dedupe_seconds * 10]
        for key in stale:
            self._seen.pop(key, None)


class TelegramErrorHandler(logging.Handler):
    """Шлёт ERROR+ логи в Telegram в фоне, не блокируя запрос."""

    def __init__(self, level=logging.ERROR, dedupe_seconds=None, max_per_minute=None):
        super().__init__(level=level)
        self.dedupe_seconds = dedupe_seconds if dedupe_seconds is not None else getattr(
            settings, "TELEGRAM_ERROR_DEDUPE_SECONDS", 300
        )
        self.max_per_minute = max_per_minute if max_per_minute is not None else getattr(
            settings, "TELEGRAM_ERROR_MAX_PER_MINUTE", 20
        )
        self._throttle = _Throttle(self.dedupe_seconds, self.max_per_minute)
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="tg-error")

    def emit(self, record):
        try:
            if not self._enabled() or record.name.startswith(IGNORED_LOGGER_PREFIXES):
                return

            fingerprint, text = self._render(record)
            allowed, suppressed = self._throttle.check(fingerprint)
            if not allowed:
                return
            if suppressed:
                text = f"{text}\n\n<i>Похожих ошибок подавлено с прошлой отправки: {suppressed}</i>"

            self._executor.submit(self._send, text)
        except Exception:  # noqa: BLE001 — хендлер логов не должен ронять приложение
            self.handleError(record)

    @staticmethod
    def _enabled():
        if not getattr(settings, "TELEGRAM_ERROR_ALERTS_ENABLED", False):
            return False
        return bool(getattr(settings, "TELEGRAM_BOT_TOKEN", "")) and bool(
            getattr(settings, "TELEGRAM_ERROR_CHAT_ID", "") or getattr(settings, "TELEGRAM_CHAT_ID", "")
        )

    @staticmethod
    def _send(text):
        from common.telegram_notifier import send_telegram_notification

        main_chat_id = getattr(settings, "TELEGRAM_CHAT_ID", "")
        chat_id = getattr(settings, "TELEGRAM_ERROR_CHAT_ID", "") or main_chat_id
        thread_id = getattr(settings, "TELEGRAM_ERROR_THREAD_ID", None)
        if thread_id is None:
            # Топик уведомлений годится только для того же чата, иначе Telegram вернёт ошибку.
            thread_id = getattr(settings, "TELEGRAM_THREAD_ID", None) if str(chat_id) == str(main_chat_id) else 0

        send_telegram_notification(text, chat_id=chat_id, thread_id=thread_id)

    def _render(self, record):
        try:
            message = record.getMessage()
        except Exception:  # noqa: BLE001
            message = str(record.msg)

        exc_text = ""
        exc_type = ""
        if record.exc_info:
            exc_type = getattr(record.exc_info[0], "__name__", "") or ""
            exc_text = "".join(traceback.format_exception(*record.exc_info))[-MAX_TRACEBACK_CHARS:]

        fingerprint = hashlib.sha1(
            "|".join([
                record.name,
                str(record.levelno),
                exc_type,
                record.pathname or "",
                str(record.lineno),
                (record.msg if isinstance(record.msg, str) else str(record.msg))[:200],
            ]).encode("utf-8", "replace")
        ).hexdigest()

        env = getattr(settings, "TELEGRAM_ERROR_ENVIRONMENT", "") or ("dev" if settings.DEBUG else "prod")
        lines = [
            f"🚨 <b>{html.escape(record.levelname)}</b> · {html.escape(env)}",
            f"<b>Логгер:</b> {html.escape(record.name)}",
            f"<b>Где:</b> {html.escape(str(record.pathname))}:{record.lineno} ({html.escape(record.funcName or '-')})",
        ]

        request = getattr(record, "request", None)
        if request is not None:
            lines.append(f"<b>Запрос:</b> {html.escape(self._request_line(request))}")
            user_ref = self._user_ref(request)
            if user_ref:
                lines.append(f"<b>Пользователь:</b> {html.escape(user_ref)}")

        if exc_type:
            lines.append(f"<b>Исключение:</b> {html.escape(exc_type)}")

        lines.append(f"\n<b>Сообщение:</b>\n{html.escape(message[:MAX_MESSAGE_CHARS])}")

        if exc_text:
            lines.append(f"\n<pre>{html.escape(exc_text)}</pre>")

        return fingerprint, "\n".join(lines)

    @staticmethod
    def _request_line(request):
        try:
            return f"{request.method} {request.get_full_path()}"
        except Exception:  # noqa: BLE001
            return "-"

    @staticmethod
    def _user_ref(request):
        try:
            user = getattr(request, "user", None)
            if user is None or not getattr(user, "is_authenticated", False):
                return ""
            return f"id={user.id} {getattr(user, 'phone_number', '') or getattr(user, 'username', '')}"
        except Exception:  # noqa: BLE001
            return ""
