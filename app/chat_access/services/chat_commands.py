from rest_framework import serializers

from account.services.stream import (
    create_stream_channel,
    show_channel_for_user,
    update_channel_extra_data,
)
from chat_access.models import Chat


def create_or_get_chat(client, specialist):
    channel_id = f"chat_{client.id}_{specialist.id}"
    chat, created = Chat.objects.get_or_create(
        client=client,
        specialist=specialist,
        defaults={"channel_id": channel_id},
    )
    if created:
        try:
            create_stream_channel(chat)
        except Exception as exc:
            chat.delete()
            raise serializers.ValidationError(f"Ошибка создания канала в GetStream: {exc}")
    else:
        update_fields = []
        was_deleted_by_client = chat.deleted_by_client_at is not None
        was_deleted_by_specialist = chat.deleted_by_specialist_at is not None
        if chat.deleted_by_client_at is not None:
            chat.deleted_by_client_at = None
            update_fields.append("deleted_by_client_at")
        if chat.deleted_by_specialist_at is not None:
            chat.deleted_by_specialist_at = None
            update_fields.append("deleted_by_specialist_at")
        if update_fields:
            chat.save(update_fields=update_fields)
            if was_deleted_by_client:
                show_channel_for_user(chat.channel_id, chat.client_id)
            if was_deleted_by_specialist:
                show_channel_for_user(chat.channel_id, chat.specialist_id)
    return chat


def update_chat_and_stream(instance, validated_data):
    for field, value in validated_data.items():
        setattr(instance, field, value)
    instance.save(update_fields=[*validated_data.keys(), "updated_at"])

    try:
        update_channel_extra_data(channel_id=instance.channel_id, data=validated_data)
    except Exception as exc:
        raise serializers.ValidationError(f"Ошибка обновления канала в GetStream: {exc}")
    return instance
