from django.conf import settings
from django.core.management.base import BaseCommand

from common.telegram_notifier import telegram_api_call


class Command(BaseCommand):
    help = "Регистрирует webhook бота уведомлений (кнопки решения по заявкам)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--base-url",
            default="",
            help="Базовый URL API, например https://example.com. По умолчанию берётся DOMAIN.",
        )
        parser.add_argument("--drop", action="store_true", help="Удалить webhook.")

    def handle(self, *args, **options):
        bot_token = getattr(settings, "TELEGRAM_BOT_TOKEN", "")
        if not bot_token:
            self.stderr.write("TELEGRAM_BOT_TOKEN не задан.")
            return

        if options["drop"]:
            telegram_api_call("deleteWebhook", {}, bot_token=bot_token)
            self.stdout.write(self.style.SUCCESS("Webhook удалён."))
            return

        secret = getattr(settings, "TELEGRAM_ADMIN_WEBHOOK_SECRET", "")
        if not secret:
            self.stderr.write("TELEGRAM_ADMIN_WEBHOOK_SECRET не задан.")
            return

        base_url = (options["base_url"] or f"https://{settings.DOMAIN}").rstrip("/")
        url = f"{base_url}/api/integration/telegram/admin/webhook/{secret}/"

        payload = {
            "url": url,
            "allowed_updates": ["message", "callback_query"],
            "drop_pending_updates": True,
        }
        secret_token = getattr(settings, "TELEGRAM_WEBHOOK_SECRET_TOKEN", "")
        if secret_token:
            payload["secret_token"] = secret_token

        result = telegram_api_call("setWebhook", payload, bot_token=bot_token)
        if result:
            self.stdout.write(self.style.SUCCESS(f"Webhook установлен: {url}"))
        else:
            self.stderr.write("Не удалось установить webhook, см. логи.")
