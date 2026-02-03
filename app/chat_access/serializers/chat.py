from django.utils import timezone
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers
from django.contrib.auth import get_user_model

from account.services import create_stream_channel
from ..models import Chat, AccessOrder

User = get_user_model()


class AccessOrderShortSerializer(serializers.ModelSerializer):
    class Meta:
        model = AccessOrder
        fields = ('id', 'activated_at', 'expires_at', 'tariff_type', 'payment_status')


class UserShortSerializer(serializers.ModelSerializer):
    """Краткий сериализатор пользователя (для отображения в чате)"""

    class Meta:
        model = User
        fields = ('id', 'first_name', 'last_name', 'photo')


class ChatListSerializer(serializers.ModelSerializer):
    companion = serializers.SerializerMethodField()
    user_role = serializers.SerializerMethodField()
    last_access_order = serializers.SerializerMethodField()
    specialist_note = serializers.SerializerMethodField()

    class Meta:
        model = Chat
        fields = (
            'id',
            'companion',
            'channel_id',
            'created_at',
            'user_role',
            'last_access_order',
            'specialist_note'
        )

    @extend_schema_field(UserShortSerializer)
    def get_companion(self, obj):
        user = self.context['request'].user
        if obj.client == user:
            return UserShortSerializer(obj.specialist).data
        elif obj.specialist == user:
            return UserShortSerializer(obj.client).data
        return None

    def get_user_role(self, obj):
        user = self.context['request'].user
        if obj.client == user:
            return "client"
        elif obj.specialist == user:
            return "specialist"
        return None

    def get_specialist_note(self, obj):
        """Заметка видна только специалисту"""
        user = self.context['request'].user
        if obj.specialist == user:
            return obj.specialist_note or ''
        return None

    @extend_schema_field(AccessOrderShortSerializer)
    def get_last_access_order(self, obj):
        user = self.context['request'].user

        # Доступ только клиенту
        if obj.client != user:
            return None

        now = timezone.now()

        last_active_order = obj.access_orders.filter(
            client=user,
            payment_status='success',
            expires_at__gt=now
        ).order_by('-created_at').first()

        if last_active_order:
            return AccessOrderShortSerializer(last_active_order).data
        return None


class ChatCreateSerializer(serializers.ModelSerializer):
    client = serializers.HiddenField(default=serializers.CurrentUserDefault())

    class Meta:
        model = Chat
        fields = (
            'id',
            'client',
            'specialist',
            'channel_id',
        )
        read_only_fields = ('client', 'channel_id')

    def create(self, validated_data):
        client = validated_data['client']
        specialist = validated_data['specialist']

        channel_id = f"chat_{client.id}_{specialist.id}"

        chat, created = Chat.objects.get_or_create(
            client=client,
            specialist=specialist,
            defaults={
                "channel_id": channel_id,
            }
        )

        if created:
            try:
                create_stream_channel(chat)
            except Exception as e:
                chat.delete()
                raise serializers.ValidationError(
                    f"Ошибка создания канала в GetStream: {e}"
                )

        return chat