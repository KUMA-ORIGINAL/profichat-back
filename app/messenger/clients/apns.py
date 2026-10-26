"""Тонкий клиент APNs для VoIP-пушей (PushKit) о входящих звонках: .p8-ключ, aioapns."""
import asyncio
import logging

from aioapns import APNs, NotificationRequest, PushType
from aioapns.common import APNS_RESPONSE_CODE, PRIORITY_HIGH
from django.conf import settings

logger = logging.getLogger(__name__)


def voip_topic() -> str:
    return f"{settings.APNS_BUNDLE_ID}.voip"


def _configured() -> bool:
    return all(
        (settings.APNS_KEY_PATH, settings.APNS_KEY_ID, settings.APNS_TEAM_ID, settings.APNS_BUNDLE_ID)
    )


async def _send(token: str, payload: dict):
    # APNs создаёт пул соединений с текущим циклом событий — только внутри корутины
    client = APNs(
        key=settings.APNS_KEY_PATH,
        key_id=settings.APNS_KEY_ID,
        team_id=settings.APNS_TEAM_ID,
        topic=voip_topic(),
        use_sandbox=settings.APNS_USE_SANDBOX,
    )
    try:
        return await client.send_notification(
            NotificationRequest(
                device_token=token,
                message=payload,
                push_type=PushType.VOIP,
                priority=int(PRIORITY_HIGH),
                # позже окончания дозвона пуш бессмыслен
                time_to_live=settings.MESSENGER_CALL_RING_TIMEOUT_SECONDS,
                apns_topic=voip_topic(),
            )
        )
    finally:
        pool = getattr(client, "pool", None)
        if pool is not None and hasattr(pool, "close"):
            pool.close()


def send_voip(token: str, payload: dict) -> bool:
    """
    VoIP-пуш на PushKit-токен. 410 (токен больше не действителен) → VoipDevice.active=False.

    Ошибки не пробрасываются: возвращается False и пишется лог.
    """
    from messenger.models import VoipDevice

    if not _configured():
        logger.warning("[VoIP] APNs не настроен (APNS_*), пуш не отправлен")
        return False
    try:
        result = asyncio.run(_send(token, payload))
    except Exception:
        logger.exception("[VoIP] APNs send failed for token=%s…", token[:8])
        return False

    if result.is_successful:
        return True
    logger.warning("[VoIP] APNs rejected token=%s… status=%s: %s", token[:8], result.status, result.description)
    if str(result.status) == APNS_RESPONSE_CODE.GONE:
        VoipDevice.objects.filter(token=token).update(active=False)
    return False
