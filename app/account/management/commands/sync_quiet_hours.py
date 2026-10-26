import logging
import time

from django.core.management.base import BaseCommand
from django.db import close_old_connections

from account.services.quiet_hours import sync_all_quiet_hours

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Тихие часы специалистов: пуши чата вне графика и сводка в начале смены"

    def add_arguments(self, parser):
        parser.add_argument(
            "--every",
            type=int,
            default=0,
            help="Повторять каждые N секунд; 0 — один проход",
        )

    def handle(self, *args, every=0, **kwargs):
        while True:
            # Процесс живёт сутками: протухшее соединение с базой иначе
            # уронило бы следующий проход.
            close_old_connections()
            try:
                sync_all_quiet_hours()
            except Exception:
                logger.exception("[QuietHours] Sync pass failed")
            if not every:
                return
            time.sleep(every)
