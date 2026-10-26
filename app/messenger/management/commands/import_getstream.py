from datetime import timezone as dt_timezone

from django.core.management.base import BaseCommand, CommandError
from django.utils.dateparse import parse_date, parse_datetime

from messenger.services.getstream_import import import_all


def _parse_since(value):
    try:
        parsed = parse_datetime(value)
        if parsed is None:
            date = parse_date(value)
            if date is not None:
                parsed = parse_datetime(f"{date.isoformat()}T00:00:00")
    except ValueError:
        parsed = None
    if parsed is None:
        raise CommandError(f"--since: ожидается дата ISO 8601, получено {value!r}")
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt_timezone.utc)
    return parsed


class Command(BaseCommand):
    help = (
        "Импорт истории переписки из GetStream в свой мессенджер. Идемпотентен: повторный запуск "
        "не создаёт дублей и докачивает недостающие вложения. Время без зоны считается UTC."
    )

    def add_arguments(self, parser):
        parser.add_argument("--channel", dest="channel_id", help="channel_id одного чата")
        parser.add_argument(
            "--since", help="Только сообщения, созданные не раньше этого момента (ISO 8601), для дельта-импорта"
        )
        parser.add_argument(
            "--dry-run", action="store_true", help="Ничего не записывать и не скачивать, только посчитать"
        )

    def handle(self, *args, channel_id=None, since=None, dry_run=False, **options):
        since_dt = _parse_since(since) if since else None
        verbosity = options.get("verbosity", 1)

        def on_channel(chat, channel_stats):
            if verbosity >= 2:
                self.stdout.write(f"{chat.channel_id}: {channel_stats.summary()}")
            for error in channel_stats.errors:
                self.stderr.write(error)

        stats = import_all(channel_id=channel_id, since=since_dt, dry_run=dry_run, on_channel=on_channel)
        if channel_id and stats.channels == 0:
            for error in stats.errors:
                self.stderr.write(error)

        prefix = "[dry-run] " if dry_run else ""
        self.stdout.write(f"{prefix}GetStream import finished: {stats.summary()}")
