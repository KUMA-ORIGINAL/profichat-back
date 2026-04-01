import logging
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone

from account.models import InviteDelivery
from chat_access.services import update_chat_data_from_order
from .sms import send_sms
from .stream import create_stream_channel
from chat_access.models import Chat, Tariff, AccessOrder
from common.notifications import send_chat_invite_push
from common.telegram_notifier import notify_new_client_registration

logger = logging.getLogger(__name__)
User = get_user_model()


def send_invite_sms(client, specialist, chat):
    invite_link = f"https://profigram.site/r/{chat.channel_id}"
    first_name = specialist.first_name or "Специалист"
    last_initial = specialist.last_name[0] + "." if specialist.last_name else ""
    text = (
        f"{first_name} {last_initial} приглашает Вас в приложение для консультаций. "
        f"Завершите регистрацию: {invite_link}"
    )
    return send_sms(phone=client.phone_number, text=text, return_meta=True)


def _safe_send_invitation(client, specialist, chat, is_new_client):
    try:
        if is_new_client:
            return send_invite_sms(client, specialist, chat)
        return send_chat_invite_push(client, chat, return_meta=True)
    except Exception as exc:
        logger.exception(
            "Invite delivery exception: specialist=%s client=%s chat=%s channel=%s",
            specialist.id,
            client.id,
            chat.id,
            InviteDelivery.CHANNEL_SMS if is_new_client else InviteDelivery.CHANNEL_PUSH,
        )
        return {
            "ok": False,
            "error_message": str(exc),
            "provider_status": "",
            "provider_message_id": "",
        }


def invite_client(phone_number: str, tariff_id: int, specialist: User, note: str = None):
    with transaction.atomic():
        client = User.objects.filter(phone_number=phone_number).first()
        is_new_client = False

        if not client:
            client = User.objects.create_user(
                phone_number=phone_number,
                is_active=True,
            )
            is_new_client = True
        elif not client.is_active:
            # Для уже существующего пользователя — убедимся, что is_active=True
            client.is_active = True
            client.save(update_fields=["is_active"])

        chat, chat_created = Chat.objects.get_or_create(
            client=client,
            specialist=specialist,
            defaults={
                "channel_id": f"chat_{client.id}_{specialist.id}",
                "specialist_note": note or "",
            },
        )

        # Обновляем заметку, если чат уже существует
        if not chat_created and note is not None and chat.specialist_note != note:
            chat.specialist_note = note
            chat.save(update_fields=["specialist_note"])

        if not chat_created:
            restore_fields = []
            if chat.deleted_by_client_at is not None:
                chat.deleted_by_client_at = None
                restore_fields.append("deleted_by_client_at")
            if chat.deleted_by_specialist_at is not None:
                chat.deleted_by_specialist_at = None
                restore_fields.append("deleted_by_specialist_at")
            if restore_fields:
                chat.save(update_fields=restore_fields)

        tariff = Tariff.objects.get(id=tariff_id)
        activated_at = timezone.now()
        access_order = AccessOrder.objects.create(
            client=client,
            specialist=specialist,
            chat=chat,
            tariff=tariff,
            price=0,
            tariff_type="free",
            payment_status="success",
            activated_at=activated_at,
            expires_at=activated_at + timedelta(hours=tariff.duration_hours),
        )

    if chat_created:
        try:
            create_stream_channel(chat=chat, first_message=specialist.invite_greeting)
        except Exception:
            # Не оставляем "битый" новый чат без канала
            chat.delete()
            raise

    try:
        update_chat_data_from_order(access_order)
    except Exception:
        logger.exception("Failed to update chat extra data from order %s", access_order.id)

    if is_new_client:
        try:
            notify_new_client_registration(client)
        except Exception as exc:
            logger.error("Failed to send Telegram notification for invited user %s: %s", client.id, exc)

    invite_result = _safe_send_invitation(
        client=client,
        specialist=specialist,
        chat=chat,
        is_new_client=is_new_client,
    )

    is_success = bool(invite_result.get("ok", False))
    delivery = InviteDelivery.objects.create(
        specialist=specialist,
        client=client,
        chat=chat,
        channel=InviteDelivery.CHANNEL_SMS if is_new_client else InviteDelivery.CHANNEL_PUSH,
        status=InviteDelivery.STATUS_SENT if is_success else InviteDelivery.STATUS_FAILED,
        is_new_client=is_new_client,
        provider_message_id=invite_result.get("provider_message_id", ""),
        provider_status=invite_result.get("provider_status", ""),
        error_message=invite_result.get("error_message", ""),
        metadata=invite_result,
    )

    if not is_success:
        logger.warning(
            "Invite delivery failed: specialist=%s client=%s chat=%s channel=%s",
            specialist.id,
            client.id,
            chat.id,
            delivery.channel,
        )

    return chat, delivery
