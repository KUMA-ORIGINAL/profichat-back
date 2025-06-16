from datetime import timedelta

from django.utils import timezone

from account.services.stream import update_channel_extra_data


def update_chat_extra_data(chat, now=None, prefetched_orders=None):
    if now is None:
        now = timezone.now()

    active_orders = prefetched_orders or chat.access_orders.filter(
        payment_status='success',
        expires_at__gt=now
    ).order_by('-expires_at')

    if active_orders:
        order = sorted(active_orders, key=lambda o: o.expires_at, reverse=True)[0]
        activated_at = order.activated_at
        expires_at = order.expires_at

        update_channel_extra_data(chat.channel_id, {
            'activatedAt': activated_at,
            'expiresAt': expires_at,
        })


def update_chat_data_from_order(order):
    now = timezone.now()
    expires_at = now + timedelta(minutes=5)

    update_channel_extra_data(order.chat.channel_id, {
        'activatedAt': str(order.activated_at),
        # 'expiresAt': str(order.expires_at),
        'expiresAt': expires_at,
    })
