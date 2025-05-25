import uuid
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.utils import timezone

from .stream import create_stream_channel
from chat_access.models import Chat, Tariff, AccessOrder
from chat_access.services.notifications import send_chat_invite_push

User = get_user_model()

def invite_client(phone_number: str, tariff_id: int, specialist: User):
    client = User.objects.filter(phone_number=phone_number).first()

    if not client:
        client = User.objects.create_user(
            phone_number=phone_number,
            is_active=False  # пока не активирован
        )
        # 3. Отправляем SMS со ссылкой на скачивание
        # send_sms_invitation(phone)

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

    if client.is_active:
        send_chat_invite_push(client, chat)

    return chat
