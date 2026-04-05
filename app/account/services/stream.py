import logging
from datetime import datetime, timedelta, timezone

from chat_access.models import Chat
from common.stream_client import chat_client

logger = logging.getLogger(__name__)


def create_stream_channel(chat, first_message: str = None):
    try:
        channel = chat_client.channel(
            channel_type="messaging",
            channel_id=chat.channel_id,
            data={
                "members": [str(chat.client.id), str(chat.specialist.id)],
                "chat_id": chat.id,
                "clientId": chat.client.id,
                "specialistId": chat.specialist.id,
                "specialist_note": chat.specialist_note,
            },
        )
        channel.create(str(chat.specialist.id))
        logger.info("[Stream] Channel created: channel_id=%s", chat.channel_id)

        if first_message:
            channel.send_message(
                {"text": first_message},
                str(chat.specialist.id),
            )
            logger.info("[Stream] First message sent for channel_id=%s", chat.channel_id)

    except Exception:
        logger.exception("[Stream] Failed to create channel channel_id=%s", chat.channel_id)


def update_channel_extra_data(
    channel_id: str,
    data: dict,
    channel_type: str = "messaging",
):
    channel = chat_client.channel(channel_type, channel_id)
    channel.update_partial(data)


def delete_stream_channel(channel_id):
    try:
        channel = chat_client.channel("messaging", channel_id)
        channel.delete()
        logger.info("[Stream] Channel deleted: channel_id=%s", channel_id)
    except Exception:
        logger.exception("[Stream] Failed to delete channel channel_id=%s", channel_id)


def hide_channel_for_user(channel_id: str, user_id: int | str) -> bool:
    try:
        channel = chat_client.channel("messaging", channel_id)
        channel.hide(str(user_id))
        logger.info("[Stream] Channel hidden: %s for user=%s", channel_id, user_id)
        return True
    except Exception:
        logger.exception("[Stream] Failed to hide channel %s for user=%s", channel_id, user_id)
        return False


def show_channel_for_user(channel_id: str, user_id: int | str) -> bool:
    try:
        channel = chat_client.channel("messaging", channel_id)
        channel.show(str(user_id))
        logger.info("[Stream] Channel shown: %s for user=%s", channel_id, user_id)
        return True
    except Exception:
        logger.exception("[Stream] Failed to show channel %s for user=%s", channel_id, user_id)
        return False


def mute_user_for_user(user_id: int | str, target_user_id: int | str) -> bool:
    try:
        chat_client.mute_user(target_id=str(target_user_id), user_id=str(user_id))
        logger.info("[Stream] User muted: actor=%s target=%s", user_id, target_user_id)
        return True
    except Exception:
        logger.exception("[Stream] Failed to mute user: actor=%s target=%s", user_id, target_user_id)
        return False


def unmute_user_for_user(user_id: int | str, target_user_id: int | str) -> bool:
    try:
        chat_client.unmute_user(target_id=str(target_user_id), user_id=str(user_id))
        logger.info("[Stream] User unmuted: actor=%s target=%s", user_id, target_user_id)
        return True
    except Exception:
        logger.exception("[Stream] Failed to unmute user: actor=%s target=%s", user_id, target_user_id)
        return False


ALLOWED_TYPES = [
    "tariffProvided",
    "tariffExpired",
    "tariffActivated",
    "chatBlocked",
]

DEFAULT_TEXTS = {
    "tariffProvided": "Доступ по тарифу предоставлен.",
    "tariffExpired": "Срок действия тарифа истёк.",
    "tariffActivated": "Тариф активирован.",
    "chatBlocked": "Чат заблокирован.",
}

COOLDOWN_SECONDS = 600


def send_system_message_once(channel_id, custom_type: str, text: str = None):
    if custom_type not in ALLOWED_TYPES:
        logger.warning("[Stream] Invalid system message type: %s", custom_type)
        return False

    try:
        chat = Chat.objects.select_related("client", "specialist").get(channel_id=channel_id)
        client_name = chat.client.get_full_name()
        specialist_name = chat.specialist.get_full_name()
    except Chat.DoesNotExist:
        logger.warning("[Stream] Chat not found for channel_id=%s", channel_id)
        return False

    if not text:
        text = DEFAULT_TEXTS[custom_type]

    try:
        channel = chat_client.channel("messaging", channel_id, data={"created_by_id": "system"})

        response = channel.query(
            limit=20,
            sort=[{"field": "created_at", "direction": -1}],
        )

        now = datetime.now(timezone.utc)

        for msg in response.get("messages", []):
            if msg.get("type") != "system":
                continue

            msg_custom_type = (
                msg.get("custom_type")
                or msg.get("customType")
                or msg.get("extraData", {}).get("customType")
                or msg.get("extraData", {}).get("custom_type")
            )

            if msg_custom_type == custom_type:
                created_at = datetime.fromisoformat(msg["created_at"].replace("Z", "+00:00"))

                if now - created_at < timedelta(seconds=COOLDOWN_SECONDS):
                    logger.info(
                        "[Stream] Duplicate system message skipped custom_type=%s channel_id=%s",
                        custom_type,
                        channel_id,
                    )
                    return False
                break

        message_data = {
            "text": text,
            "type": "system",
            "custom_type": custom_type,
            "extraData": {
                "customType": custom_type,
                "custom_type": custom_type,
                "client_name": client_name,
                "specialist_name": specialist_name,
            },
        }

        channel.send_message(message_data, user_id="system")
        logger.info("[Stream] System message sent custom_type=%s channel_id=%s", custom_type, channel_id)
        return True

    except Exception:
        logger.exception(
            "[Stream] Failed to send system message custom_type=%s channel_id=%s",
            custom_type,
            channel_id,
        )
        return False

