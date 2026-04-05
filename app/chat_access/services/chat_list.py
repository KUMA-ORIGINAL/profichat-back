import logging

from django.utils import timezone

from common.stream_client import chat_client

logger = logging.getLogger(__name__)


def get_user_role(chat, user):
    if chat.client_id == user.id:
        return "client"
    if chat.specialist_id == user.id:
        return "specialist"
    return None


def get_companion(chat, user):
    if chat.client_id == user.id:
        return chat.specialist
    if chat.specialist_id == user.id:
        return chat.client
    return None


def get_last_access_order(chat, user):
    if chat.client_id != user.id:
        return None

    prefetched = getattr(chat, "prefetched_active_access_orders", None)
    if prefetched is not None:
        return prefetched[0] if prefetched else None

    return (
        chat.access_orders.filter(
            client=user,
            payment_status="success",
            expires_at__gt=timezone.now(),
        )
        .order_by("-created_at")
        .first()
    )


def get_latest_invite_delivery(chat, user):
    if chat.specialist_id != user.id:
        return None
    prefetched = getattr(chat, "prefetched_invite_deliveries", None)
    if prefetched is not None:
        return prefetched[0] if prefetched else None
    return chat.invite_deliveries.order_by("-created_at").first()


def get_specialist_note(chat, user):
    if chat.specialist_id == user.id:
        return chat.specialist_note or ""
    return None


def get_should_reply(chat, user):
    try:
        channel = chat_client.channel("messaging", chat.channel_id)
        response = channel.query(
            limit=1,
            sort=[{"field": "created_at", "direction": -1}],
        )
        messages = response.get("messages", [])
        if not messages:
            return False

        last_message = messages[0]
        if last_message.get("type") == "system":
            return False

        sender_id = last_message.get("user", {}).get("id") or last_message.get("user_id")
        return str(sender_id) != str(user.id)
    except Exception:
        logger.exception(
            "Failed to compute should_reply for channel_id=%s user_id=%s",
            chat.channel_id,
            user.id,
        )
        return False


def _extract_channel_id(channel_payload):
    channel_data = channel_payload.get("channel", {})
    return channel_data.get("id") or channel_payload.get("channel_id") or channel_payload.get("id")


def _extract_last_message(channel_payload):
    messages = channel_payload.get("messages", [])
    if messages:
        return messages[0]
    state_messages = channel_payload.get("state", {}).get("messages", [])
    if state_messages:
        return state_messages[-1]
    return None


def get_should_reply_map(chats, user):
    channel_ids = [chat.channel_id for chat in chats]
    should_reply_map = {channel_id: False for channel_id in channel_ids}

    if not channel_ids:
        return should_reply_map

    try:
        response = chat_client.query_channels(
            filter_conditions={"type": "messaging", "id": {"$in": channel_ids}},
            sort=[{"field": "last_message_at", "direction": -1}],
            watch=False,
            state=True,
            presence=False,
            message_limit=1,
            member_limit=0,
            limit=len(channel_ids),
        )
        channels = response.get("channels", []) if isinstance(response, dict) else []
    except Exception:
        logger.exception(
            "Failed to fetch channels for should_reply_map user_id=%s channel_ids_count=%s",
            user.id,
            len(channel_ids),
        )
        return should_reply_map

    for channel_payload in channels:
        channel_id = _extract_channel_id(channel_payload)
        if not channel_id:
            continue

        last_message = _extract_last_message(channel_payload)
        if not last_message or last_message.get("type") == "system":
            continue

        sender_id = last_message.get("user", {}).get("id") or last_message.get("user_id")
        should_reply_map[channel_id] = str(sender_id) != str(user.id)

    return should_reply_map


def build_chat_list_item(chat, user, should_reply_map=None):
    invite_delivery = get_latest_invite_delivery(chat, user)
    invite_delivery_payload = None
    if invite_delivery:
        invite_delivery_payload = {
            "id": invite_delivery.id,
            "created_at": invite_delivery.created_at,
            "channel": invite_delivery.channel,
            "status": invite_delivery.status,
            "provider_status": invite_delivery.provider_status,
            "error_message": invite_delivery.error_message,
            "is_new_client": invite_delivery.is_new_client,
        }

    return {
        "id": chat.id,
        "companion": get_companion(chat, user),
        "channel_id": chat.channel_id,
        "created_at": chat.created_at,
        "user_role": get_user_role(chat, user),
        "last_access_order": get_last_access_order(chat, user),
        "specialist_note": get_specialist_note(chat, user),
        "latest_invite_delivery": invite_delivery_payload,
        "should_reply": (
            should_reply_map.get(chat.channel_id, False)
            if should_reply_map is not None
            else get_should_reply(chat, user)
        ),
    }

