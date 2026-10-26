import os

from celery import Celery
from celery.schedules import crontab

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

app = Celery("config")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()

app.conf.beat_schedule = {
    "cleanup-pending-attachments": {
        "task": "messenger.tasks.cleanup_pending_attachments",
        "schedule": crontab(minute=0),  # ежечасно
    },
    "reconcile-calls": {
        "task": "messenger.tasks.reconcile_calls",
        "schedule": 60.0,  # ежеминутно: зависшие RINGING/ACCEPTED звонки
    },
}
