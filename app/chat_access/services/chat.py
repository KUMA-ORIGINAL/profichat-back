from django.utils import timezone

from account.services.stream import update_channel_extra_data


def _as_iso(value):
    if value is None:
        return None
    return value.isoformat()


def update_chat_extra_data(chat, now=None, prefetched_orders=None):
    if now is None:
        now = timezone.now()

    if prefetched_orders is not None:
        if not prefetched_orders:
            return
        order = max(prefetched_orders, key=lambda o: o.expires_at)
    else:
        order = (
            chat.access_orders.filter(
                payment_status="success",
                expires_at__gt=now,
            )
            .select_related("tariff")
            .order_by("-expires_at")
            .first()
        )
    if not order:
        return

    update_channel_extra_data(
        chat.channel_id,
        {
            "tariffName": order.tariff.name,
            "activatedAt": _as_iso(order.activated_at),
            "expiresAt": _as_iso(order.expires_at),
        },
    )


def update_chat_data_from_order(order):
    if not order.chat_id:
        return
    update_channel_extra_data(
        order.chat.channel_id,
        {
            "tariffName": order.tariff.name,
            "activatedAt": _as_iso(order.activated_at),
            "expiresAt": _as_iso(order.expires_at),
        },
    )
