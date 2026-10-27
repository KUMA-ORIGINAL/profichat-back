import logging

from django.conf import settings

from common.media import absolute_media_url
from common.notifications import send_data_push, send_push
from messenger.clients import apns
from messenger.models import Attachment, Call, ChatMember, Message, VoipDevice

logger = logging.getLogger(__name__)

ATTACHMENT_PREVIEWS = {
    Attachment.Kind.VOICE: "Голосовое сообщение",
    Attachment.Kind.IMAGE: "Фото",
    Attachment.Kind.VIDEO: "Видео",
    Attachment.Kind.FILE: "Файл",
}
DEFAULT_PREVIEW = "Сообщение"


def sender_display_name(user) -> str:
    full_name = " ".join(part for part in (user.first_name, user.last_name) if part).strip()
    return full_name or user.username or DEFAULT_PREVIEW


def user_photo_url(user) -> str | None:
    """Абсолютный URL фото пользователя (`https://<DOMAIN>/media/...`, как companion.photo); None, если фото нет."""
    return absolute_media_url(user.photo)


def message_preview(message) -> str:
    """Текст пуша: текст сообщения или подпись по типу первого вложения."""
    if message.text:
        return message.text
    attachment = message.attachments.order_by("position", "created_at", "pk").first()
    if attachment is not None:
        return ATTACHMENT_PREVIEWS.get(attachment.kind, ATTACHMENT_PREVIEWS[Attachment.Kind.FILE])
    return DEFAULT_PREVIEW


def send_message_push(message_id: int) -> None:
    """
    Пуш о новом сообщении собеседнику отправителя.

    Не отправляется для системных/звонковых/удалённых сообщений и если у получателя чат без
    уведомлений (`ChatMember.muted`, выставляется чёрным списком). В ленту Notification не пишется.
    """
    message = Message.objects.select_related("chat", "sender").filter(pk=message_id).first()
    if (
        message is None
        or message.sender_id is None
        or message.type != Message.Type.REGULAR
        or message.deleted_at is not None
    ):
        return

    chat = message.chat
    recipient_id = chat.specialist_id if message.sender_id == chat.client_id else chat.client_id
    member = ChatMember.objects.select_related("user").filter(chat=chat, user_id=recipient_id).first()
    if member is None or member.muted:
        return

    sender_name = sender_display_name(message.sender)
    send_push(
        user=member.user,
        title=sender_name,
        message=message_preview(message),
        extra={
            "type": "chat_message",
            "channelId": chat.channel_id,
            "messageId": message.id,
            "senderId": message.sender_id,
            "senderName": sender_name,
        },
        log_prefix="[Push][Message]",
        thread_id=chat.channel_id,
    )


def incoming_call_payload(call) -> dict:
    """Данные пуша о входящем звонке (одинаковые для iOS VoIP и Android data-only)."""
    return {
        "type": "incoming_call",
        "callId": str(call.pk),
        "channelId": call.chat.channel_id,
        "kind": call.kind,
        "callerId": call.caller_id,
        "callerName": sender_display_name(call.caller),
        "callerPhoto": user_photo_url(call.caller),
    }


def send_call_push(call_id) -> None:
    """
    Пуш о входящем звонке вызываемому, пока звонок ещё звонит.

    iOS — VoIP (PushKit) на все активные VoipDevice; Android — FCM data-only, priority high,
    TTL = таймаут дозвона (FCM-токены iOS-устройств получают тот же data-only, приложение его игнорирует).
    """
    call = Call.objects.select_related("chat", "caller", "callee").filter(pk=call_id).first()
    if call is None or call.status != Call.Status.RINGING:
        return

    payload = incoming_call_payload(call)
    for token in VoipDevice.objects.filter(user_id=call.callee_id, active=True).values_list("token", flat=True):
        apns.send_voip(token, payload)
    send_data_push(
        call.callee,
        payload,
        ttl_seconds=settings.MESSENGER_CALL_RING_TIMEOUT_SECONDS,
        log_prefix="[Push][Call]",
    )
