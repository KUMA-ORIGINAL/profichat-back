"""Синхронизация справочника организаций из ErkinAI (запускается по крону).

    manage.py sync_erkinai_organizations           # инкрементально
    manage.py sync_erkinai_organizations --full    # полный проход

Инкрементальный запуск дёшев — гоняйте хоть каждые 10 минут. Полный нужен
примерно раз в сутки: фид не сообщает о жёстком удалении, и только полный
проход подберёт пропавшие филиалы.
"""

from django.core.management.base import BaseCommand, CommandError

from integrations.erkinai import client
from integrations.erkinai.organization_sync import sync_organizations


class Command(BaseCommand):
    help = "Забирает организации и филиалы из ErkinAI в справочник ProfiChat."

    def add_arguments(self, parser):
        parser.add_argument(
            "--full",
            action="store_true",
            help="Полный проход без окна updated_since.",
        )

    def handle(self, *args, **options):
        try:
            result = sync_organizations(full=options["full"])
        except client.ErkinAIDisabled as exc:
            # Не ошибка: на этом стенде интеграции просто нет. Крон не должен
            # каждые десять минут падать и слать письма.
            self.stdout.write(self.style.WARNING(str(exc)))
            return
        except client.ErkinAIError as exc:
            raise CommandError(str(exc))

        self.stdout.write(self.style.SUCCESS(f"Организации ErkinAI: {result}"))
