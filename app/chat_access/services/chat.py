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
        is_active = True
        tariff_duration = order.duration_hours or 0
        time_left_seconds = (order.expires_at - now).total_seconds()
        time_left_hours = round(time_left_seconds / 3600, 2)
    else:
        is_active = False
        tariff_duration = 0
        time_left_hours = 0

    update_channel_extra_data(chat.channel_id, {
        'isActive': is_active,
        'tariffDuration': tariff_duration,
        'timeLeft': time_left_hours
    })


def update_chat_data_from_order(order):
    now = timezone.now()
    time_left_seconds = (order.expires_at - now).total_seconds()
    time_left_hours = round(time_left_seconds / 3600, 2)

    update_channel_extra_data(order.chat.channel_id, {
        'isActive': True,
        'tariffDuration': order.duration_hours or 0,
        'timeLeft': time_left_hours
    })
