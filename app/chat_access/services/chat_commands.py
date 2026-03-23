from rest_framework import serializers

from account.services.stream import create_stream_channel, update_channel_extra_data
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
