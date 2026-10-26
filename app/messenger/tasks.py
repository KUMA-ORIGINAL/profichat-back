# Celery-задачи мессенджера (autodiscover подхватывает этот модуль).
import logging

from celery import shared_task

from messenger.clients import centrifugo

logger = logging.getLogger(__name__)


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


@shared_task(ignore_result=True)
def cleanup_pending_attachments():
    """Удаляет не отправленные вложения (PENDING старше 24 часов) вместе с объектами в хранилище."""
    from messenger.services import attachments

    return attachments.cleanup_pending()


@shared_task(ignore_result=True)
def send_call_push(call_id):
    """Пуш о входящем звонке: iOS VoIP (PushKit) и Android data-only."""
    from messenger.services.push import send_call_push as _send_call_push

    _send_call_push(call_id)


@shared_task(ignore_result=True)
def expire_call(call_id):
    """Таймаут дозвона: RINGING → MISSED + пуш «Пропущенный звонок»."""
    from messenger.services import calls

    calls.expire_call(call_id)


@shared_task(ignore_result=True)
def check_call_room(call_id):
    """Повторная проверка комнаты после participant_left, если LiveKit тогда не ответил."""
    from messenger.services import calls

    calls.check_call_room(call_id)


@shared_task(ignore_result=True)
def reconcile_calls():
    """Ежеминутно: завершает зависшие RINGING/ACCEPTED звонки (потерянные таймауты и вебхуки)."""
    from messenger.services import calls

    return calls.reconcile_calls()


@shared_task(ignore_result=True)
def delete_call_room(room_name):
    """Закрывает комнату LiveKit завершённого звонка (пустая комната и так закроется по empty_timeout)."""
    from messenger.clients import livekit

    try:
        livekit.delete_room(room_name)
    except livekit.LiveKitError:
        logger.warning("LiveKit delete_room failed for %s", room_name, exc_info=True)
