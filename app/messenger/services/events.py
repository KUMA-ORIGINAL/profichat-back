import logging
from collections.abc import Iterable

from django.db import transaction
from djangorestframework_camel_case.util import camelize

from messenger import tasks
from messenger.clients import centrifugo

logger = logging.getLogger(__name__)

RETRY_COUNTDOWN = 2  # секунд до первой повторной попытки


def personal_channel(user_id) -> str:
    return f"personal:{user_id}"


def publish(user_ids: Iterable[int], event_type: str, data: dict) -> None:
    """
    Публикует событие в личные каналы пользователей после коммита транзакции.

    Конверт: {"type": event_type, "data": camelize(data)}. Ошибка Centrifugo не ломает запрос:
    пишем в лог и повторяем публикацию Celery-задачей.
    """
    channels = [personal_channel(user_id) for user_id in user_ids]
    if not channels:
        return
    envelope = {"type": event_type, "data": camelize(data)}

    def _send():
        try:
            centrifugo.broadcast(channels, envelope)
        except centrifugo.CentrifugoError:
            logger.warning("Centrifugo broadcast failed for %s, scheduling retry", event_type, exc_info=True)
            try:
                tasks.publish_event.apply_async(args=[channels, envelope], countdown=RETRY_COUNTDOWN)
            except Exception:
                logger.exception("Failed to schedule publish_event retry for %s", event_type)
        except Exception:
            # не-Centrifugo ошибка (например, не-JSON данные) — повтор не поможет; запрос уже закоммичен
            logger.exception("Failed to publish %s", event_type)

    transaction.on_commit(_send)
