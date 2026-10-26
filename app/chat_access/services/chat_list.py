from django.db.models import F, Prefetch
from django.utils import timezone

from account.models import InviteDelivery
from chat_access.models import AccessOrder, BlockedChat, FavoriteChat
from messenger.models import ChatMember, Message


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
    """Нужно ли пользователю ответить: последнее сообщение обычное и не от него (по данным БД)."""
    last_message = chat.last_message
    if last_message is None or last_message.type != Message.Type.REGULAR:
        return False
    return last_message.sender_id is not None and last_message.sender_id != user.id


def get_should_reply_map(chats, user):
    return {chat.channel_id: get_should_reply(chat, user) for chat in chats}


def get_member(chat, user):
    prefetched = getattr(chat, "prefetched_my_members", None)
    if prefetched is not None:
        return prefetched[0] if prefetched else None
    return chat.member_for(user)


def _is_marked(chat, user, prefetch_attr, related_name):
    prefetched = getattr(chat, prefetch_attr, None)
    if prefetched is not None:
        return bool(prefetched)
    return getattr(chat, related_name).filter(user=user).exists()


def get_tariff(chat):
    """Последний оплаченный доступ чата (как extraData канала в Stream); истёкший тоже отдаётся."""
    prefetched = getattr(chat, "prefetched_paid_access_orders", None)
    if prefetched is not None:
        order = prefetched[0] if prefetched else None
    else:
        order = (
            chat.access_orders.filter(payment_status="success")
            .select_related("tariff")
            .order_by("-expires_at", "-created_at")
            .first()
        )
    if order is None:
        return None
    return {
        "name": order.tariff.name if order.tariff_id else "",
        "activated_at": order.activated_at,
        "expires_at": order.expires_at,
    }


def chat_list_queryset(base_qs, user):
    """Подгрузка всего, что нужно `build_chat_list_item`, без запросов на каждый чат."""
    now = timezone.now()
    return base_qs.select_related(
        "client", "specialist", "last_message", "last_message__reply_to"
    ).prefetch_related(
        Prefetch(
            "invite_deliveries",
            queryset=InviteDelivery.objects.order_by("-created_at"),
            to_attr="prefetched_invite_deliveries",
        ),
        Prefetch(
            "access_orders",
            queryset=AccessOrder.objects.filter(
                payment_status="success",
                expires_at__gt=now,
            ).order_by("-created_at"),
            to_attr="prefetched_active_access_orders",
        ),
        Prefetch(
            "access_orders",
            queryset=AccessOrder.objects.filter(payment_status="success")
            .select_related("tariff")
            .order_by("-expires_at", "-created_at"),
            to_attr="prefetched_paid_access_orders",
        ),
        Prefetch(
            "members",
            queryset=ChatMember.objects.filter(user=user),
            to_attr="prefetched_my_members",
        ),
        Prefetch(
            "favorites",
            queryset=FavoriteChat.objects.filter(user=user),
            to_attr="prefetched_my_favorites",
        ),
        Prefetch(
            "blocked_entries",
            queryset=BlockedChat.objects.filter(user=user),
            to_attr="prefetched_my_blocks",
        ),
    ).order_by(F("last_message_at").desc(nulls_last=True), "-created_at")


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

    member = get_member(chat, user)
    last_message = chat.last_message
    if last_message is not None:
        last_message.chat = chat  # channel_id без лишнего запроса

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
        "last_message": last_message,
        "last_message_at": chat.last_message_at,
        "unread_count": member.unread_count if member else 0,
        "is_favorite": _is_marked(chat, user, "prefetched_my_favorites", "favorites"),
        "is_blocked": _is_marked(chat, user, "prefetched_my_blocks", "blocked_entries"),
        "client_can_send_voice": chat.client_can_send_voice,
        "tariff": get_tariff(chat),
    }

