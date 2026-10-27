"""
Присутствие собеседника: `lastActiveAt` (наша БД) и `isOnline` (presence личного канала в Centrifugo).

Событий о появлении/уходе пользователя нет: приложение обновляет статус перезапросом списка/чата,
а внутри открытого чата видит собеседника через presence канала `chat:<channelId>`.
"""
import logging
from collections.abc import Iterable

from django.core.cache import cache
from django.db import transaction
from django.utils import timezone

from messenger.clients import centrifugo
from messenger.models import UserPresence
from messenger.services.events import personal_channel

logger = logging.getLogger(__name__)

TOUCH_INTERVAL = 60  # секунд: не чаще одной записи в минуту на пользователя


def throttle_key(user_id) -> str:
    return f"messenger:presence:touch:{user_id}"


def touch(user_id) -> None:
    """
    Отметить активность пользователя (upsert last_active_at). Не чаще раза в TOUCH_INTERVAL
    (guard в кэше). Никогда не ломает запрос: ошибки — в лог.
    """
    try:
        if not cache.add(throttle_key(user_id), 1, timeout=TOUCH_INTERVAL):
            return
        with transaction.atomic():  # savepoint: ошибка не портит транзакцию запроса
            UserPresence.objects.bulk_create(
                [UserPresence(user_id=user_id, last_active_at=timezone.now())],
                update_conflicts=True,
                unique_fields=["user"],
                update_fields=["last_active_at"],
            )
    except Exception:
        logger.warning("Failed to update presence of user %s", user_id, exc_info=True)


def online_user_ids(user_ids: Iterable[int]) -> set[int]:
    """
    Кто из пользователей сейчас подключён к Centrifugo (есть в presence `personal:<id>`).

    Один batch-запрос на всех; при любой ошибке — все «не в сети» (warning в лог).
    """
    ids = sorted(set(user_ids))
    if not ids:
        return set()
    channels = {personal_channel(user_id): user_id for user_id in ids}
    try:
        stats = centrifugo.presence_stats_batch(list(channels))
    except Exception:
        logger.warning("Centrifugo presence_stats batch failed for %s users", len(ids), exc_info=True)
        return set()
    return {user_id for channel, user_id in channels.items() if (stats.get(channel) or 0) > 0}
