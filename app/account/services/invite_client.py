import logging
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone

from account.models import InviteDelivery
from chat_access.services import update_chat_data_from_order
from .notify import send_notification
from .stream import create_stream_channel
from chat_access.models import Chat, Tariff, AccessOrder
from common.notifications import send_chat_invite_push
from common.telegram_notifier import notify_new_client_registration

logger = logging.getLogger(__name__)
User = get_user_model()


def send_invite_sms(client, specialist, chat, access_order):
    invite_link = f"https://profigram.site/r/{chat.channel_id}"
    doctor_name = f"{specialist.first_name} {specialist.last_name}".strip() or "Специалист"
    org_name = specialist.organization.name if specialist.organization_id else ""
    access_period = f"{access_order.tariff.duration_hours} ч."
    return send_notification(
        phone=str(client.phone_number),
        scenario="invite_profigram",
        variables={
            "doctor_name": doctor_name,
            "org_name": org_name,
            "access_period": access_period,
            "chat_link": invite_link,
            "order_id": access_order.id,
        },
        external_id=f"invite-{access_order.id}",
        return_meta=True,
    )


def _send_via(channel, client, specialist, chat, access_order):
    try:
        if channel == InviteDelivery.CHANNEL_SMS:
            return send_invite_sms(client, specialist, chat, access_order)
        return send_chat_invite_push(client, chat, return_meta=True)
    except Exception as exc:
        logger.exception(
            "Invite delivery exception: specialist=%s client=%s chat=%s channel=%s",
            specialist.id,
            client.id,
            chat.id,
            channel,
        )
        return {
            "ok": False,
            "error_message": str(exc),
            "provider_status": "",
            "provider_message_id": "",
        }


def _safe_send_invitation(client, specialist, chat, access_order, is_new_client):
    if is_new_client:
        channel = InviteDelivery.CHANNEL_SMS
        result = _send_via(channel, client, specialist, chat, access_order)
        return channel, result

    channel = InviteDelivery.CHANNEL_PUSH
    result = _send_via(channel, client, specialist, chat, access_order)
    if not result.get("ok"):
        logger.info(
            "Push delivery failed for client=%s, falling back to SMS",
            client.id,
        )
        channel = InviteDelivery.CHANNEL_SMS
        result = _send_via(channel, client, specialist, chat, access_order)
    return channel, result


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

    channel, invite_result = _safe_send_invitation(
        client=client,
        specialist=specialist,
        chat=chat,
        access_order=access_order,
        is_new_client=is_new_client,
    )

    is_success = bool(invite_result.get("ok", False))
    delivery = InviteDelivery.objects.create(
        specialist=specialist,
        client=client,
        chat=chat,
        channel=channel,
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
