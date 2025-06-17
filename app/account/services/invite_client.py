import uuid
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.utils import timezone

from chat_access.services import update_chat_data_from_order
from .sms import send_sms
from .stream import create_stream_channel
from chat_access.models import Chat, Tariff, AccessOrder
from common.notifications import send_chat_invite_push

User = get_user_model()


def invite_client(phone_number: str, tariff_id: int, specialist: User):
    client = User.objects.filter(phone_number=phone_number).first()

    if not client:
        client = User.objects.create_user(
            phone_number=phone_number,
            is_active=False
        )
        invite_link = f"https://profigram.site/profigramlinks/specialist/{specialist.id}"
        text = f"{specialist.get_full_name()} пригласил в Profigram. Завершите регистрацию по ссылке: {invite_link}"
        send_sms(phone=client.phone_number, text=text)

    chat = Chat.objects.filter(
        client=client,
        specialist=specialist,
    ).first()
    if not chat:
        chat = Chat.objects.create(
            client=client,
            specialist=specialist,
            channel_id=f"chat_{uuid.uuid4().hex}"
        )
        create_stream_channel(chat)

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

    if client.is_active:
        send_chat_invite_push(client, chat)

    return chat
