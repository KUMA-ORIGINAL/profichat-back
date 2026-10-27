import logging
from collections.abc import Iterable

from django.db import transaction
from djangorestframework_camel_case.util import camelize
from rest_framework import serializers

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


def format_datetime(value):
    """Дата как в REST-ответах (DRF DateTimeField: ISO, часовой пояс проекта) или None."""
    return serializers.DateTimeField().to_representation(value) if value is not None else None


def chat_updated_payload(chat, user) -> dict:
    """
    Данные `chat.updated` для одного участника — те же значения, что в списке чатов.

    `specialist_note` отдаётся только специалисту; `is_favorite`/`is_blocked`/`pinned_at` — свои у каждого.
    """
    from chat_access.serializers.chat import ChatTariffSerializer
    from chat_access.services.chat_list import build_chat_list_item

    # shouldReply в chat.updated не входит: пустая карта — без запроса к GetStream в legacy-режиме
    item = build_chat_list_item(chat, user, should_reply_map={})
    data = {
        "channel_id": item["channel_id"],
        "client_can_send_voice": item["client_can_send_voice"],
        "tariff": dict(ChatTariffSerializer(item["tariff"]).data) if item["tariff"] else None,
        "is_favorite": item["is_favorite"],
        "is_blocked": item["is_blocked"],
        "pinned_at": format_datetime(item["pinned_at"]),
    }
    if chat.specialist_id == user.pk:
        data["specialist_note"] = item["specialist_note"]
    return data


def publish_chat_updated_to(chat, user) -> None:
    """`chat.updated` только своим устройствам пользователя (после коммита)."""
    publish([user.pk], "chat.updated", chat_updated_payload(chat, user))


def publish_chat_updated(chat) -> None:
    """`chat.updated` обоим участникам: отдельный payload каждому (после коммита)."""
    for user in (chat.client, chat.specialist):
        publish([user.pk], "chat.updated", chat_updated_payload(chat, user))
