import logging
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from account.services.stream import ALLOWED_TYPES, COOLDOWN_SECONDS, DEFAULT_TEXTS
from chat_access.models import Chat
from messenger.models import Message
from messenger.services import messages as message_service

logger = logging.getLogger(__name__)

# Статусы тарифа: повтор пропускается, если последнее тарифное системное сообщение чата того же типа
# (раньше старое приложение хранило это в `lastTariffStatusMessage` данных канала Stream).
TARIFF_TYPES = ("tariffProvided", "tariffExpired", "tariffActivated")


def send_system_message_once(chat, custom_type: str, text: str | None = None) -> Message | None:
    """
    Системное сообщение в чат (sender=None) с дедупликацией.

    Тип из `ALLOWED_TYPES`, текст по умолчанию из `DEFAULT_TEXTS`. Дедуп:
    - тарифные типы (`TARIFF_TYPES`): пропуск, если последнее неудалённое тарифное системное сообщение
      этого чата того же типа — без ограничения по времени (expired → expired пропускается всегда);
    - остальные (`chatBlocked`): повтор того же типа в течение `COOLDOWN_SECONDS` пропускается.
    Возвращает созданное сообщение или None (неверный тип/дубль).
    """
    if custom_type not in ALLOWED_TYPES:
        logger.warning("Invalid system message type: %s", custom_type)
        return None

    with transaction.atomic():
        # блокировка строки чата: два одновременных запроса не создадут два сообщения
        chat = Chat.objects.select_for_update().select_related("client", "specialist").get(pk=chat.pk)
        if custom_type in TARIFF_TYPES:
            latest_tariff_type = (
                Message.objects.filter(
                    chat=chat,
                    type=Message.Type.SYSTEM,
                    custom_type__in=TARIFF_TYPES,
                    deleted_at__isnull=True,
                )
                .order_by("-created_at", "-id")
                .values_list("custom_type", flat=True)
                .first()
            )
            duplicate = latest_tariff_type == custom_type
        else:
            cutoff = timezone.now() - timedelta(seconds=COOLDOWN_SECONDS)
            duplicate = Message.objects.filter(
                chat=chat,
                type=Message.Type.SYSTEM,
                custom_type=custom_type,
                created_at__gte=cutoff,
            ).exists()
        if duplicate:
            logger.info("Duplicate system message skipped custom_type=%s chat=%s", custom_type, chat.pk)
            return None

        return message_service.create_system_message(
            chat,
            custom_type,
            text or DEFAULT_TEXTS[custom_type],
            extra_data={
                "customType": custom_type,
                "clientName": chat.client.get_full_name(),
                "specialistName": chat.specialist.get_full_name(),
            },
        )
