from datetime import timedelta

from django.contrib.auth import get_user_model
from django.utils import timezone

from chat_access.services import update_chat_data_from_order
from .sms import send_sms
from .stream import create_stream_channel
from chat_access.models import Chat, Tariff, AccessOrder
from common.notifications import send_chat_invite_push

User = get_user_model()


def send_invite_sms(client, specialist, chat):
    invite_link = f"https://profigram.site/r/{chat.channel_id}"
    last_initial = specialist.last_name[0] + '.' if specialist.last_name else ''
    text = f"{specialist.first_name} {last_initial} приглашает Вас в приложение для консультаций. Завершите регистрацию: {invite_link}"
    send_sms(phone=client.phone_number, text=text)


def invite_client(phone_number: str, tariff_id: int, specialist: User, note: str = None):
    client = User.objects.filter(phone_number=phone_number).first()
    is_new_client = False

    if not client:
        client = User.objects.create_user(
            phone_number=phone_number,
            is_active=True  # теперь всегда True
        )
        is_new_client = True
    else:
        # Для уже существующего пользователя — убедимся, что is_active=True
        if not client.is_active:
            client.is_active = True
            client.save(update_fields=['is_active'])

    chat = Chat.objects.filter(
        client=client,
        specialist=specialist,
    ).first()
    if not chat:
        chat = Chat.objects.create(
            client=client,
            specialist=specialist,
            channel_id=f"chat_{client.id}_{specialist.id}",
            specialist_note=note or ''
        )
        create_stream_channel(chat=chat, first_message=specialist.invite_greeting)
    else:
        # Обновляем заметку, если чат уже существует
        if note is not None:
            chat.specialist_note = note
            chat.save(update_fields=['specialist_note'])

    tariff = Tariff.objects.get(id=tariff_id)
    access_order = AccessOrder.objects.create(
        client=client,
        specialist=specialist,
        chat=chat,
        tariff=tariff,
        price=0,
        tariff_type='free',
        payment_status='success',
        activated_at=timezone.now(),
        expires_at=timezone.now() + timedelta(hours=tariff.duration_hours),
    )
    update_chat_data_from_order(access_order)

    # Для новых пользователей — только SMS, для существующих — push
    if is_new_client:
        send_invite_sms(client, specialist, chat)
    else:
        send_chat_invite_push(client, chat)

    return chat
