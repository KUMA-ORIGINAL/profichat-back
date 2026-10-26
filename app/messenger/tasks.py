# Celery-задачи мессенджера (autodiscover подхватывает этот модуль).
from celery import shared_task

from messenger.clients import centrifugo


@shared_task(
    autoretry_for=(centrifugo.CentrifugoError,),
    retry_backoff=2,
    retry_backoff_max=60,
    retry_jitter=True,
    max_retries=5,
)
def publish_event(channels, envelope):
    """Повторная публикация события в Centrifugo, если первая попытка из on_commit не удалась."""
    centrifugo.broadcast(channels, envelope)


@shared_task(ignore_result=True)
def send_message_push(message_id):
    """FCM-пуш получателю нового сообщения (без записи в ленту уведомлений)."""
    from messenger.services.push import send_message_push as _send_message_push

    _send_message_push(message_id)
