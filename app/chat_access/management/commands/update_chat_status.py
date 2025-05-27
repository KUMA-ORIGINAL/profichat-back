from django.core.management.base import BaseCommand
from django.utils import timezone
from django.db.models import Prefetch

from chat_access.models import Chat, AccessOrder
from chat_access.services import update_chat_extra_data


class Command(BaseCommand):
    help = 'Обновляет extra_data всех чатов на основе активных заказов'

    def handle(self, *args, **kwargs):
        now = timezone.now()

        active_orders_qs = AccessOrder.objects.filter(
            payment_status='success',
            expires_at__gt=now
        )

        chats = Chat.objects.prefetch_related(
            Prefetch('access_orders', queryset=active_orders_qs, to_attr='prefetched_active_orders')
        )

        updated = 0
        for chat in chats:
            update_chat_extra_data(chat, now=now, prefetched_orders=chat.prefetched_active_orders)
            updated += 1

        self.stdout.write(
            self.style.SUCCESS(f"Обновлено {updated} чатов.")
        )
