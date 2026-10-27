from rest_framework import serializers
from django.contrib.auth import get_user_model

from messenger.serializers import MessageSerializer
from ..models import Chat, AccessOrder, BlockedChat, FavoriteChat

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


class ChatCompanionSerializer(serializers.Serializer):
    """Собеседник в объекте чата (`build_companion`): телефон — только специалисту чата."""

    id = serializers.IntegerField()
    first_name = serializers.CharField(allow_null=True)
    last_name = serializers.CharField(allow_null=True)
    middle_name = serializers.CharField(allow_null=True)
    photo = serializers.ImageField(allow_null=True)
    phone_number = serializers.CharField(allow_null=True)
    last_active_at = serializers.DateTimeField(allow_null=True)
    is_online = serializers.BooleanField()


class ChatTariffSerializer(serializers.Serializer):
    """Последний оплаченный доступ чата (раньше — extraData канала в Stream)."""

    name = serializers.CharField()
    activated_at = serializers.DateTimeField(allow_null=True)
    expires_at = serializers.DateTimeField(allow_null=True)


class ChatListSerializer(serializers.ModelSerializer):
    companion = ChatCompanionSerializer(allow_null=True)
    user_role = serializers.CharField()
    last_access_order = AccessOrderShortSerializer(allow_null=True)
    specialist_note = serializers.CharField(allow_null=True)
    latest_invite_delivery = serializers.DictField(allow_null=True)
    should_reply = serializers.BooleanField()
    last_message = MessageSerializer(allow_null=True)
    last_message_at = serializers.DateTimeField(allow_null=True)
    unread_count = serializers.IntegerField()
    last_read_message_id = serializers.IntegerField(allow_null=True)
    companion_last_read_message_id = serializers.IntegerField(allow_null=True)
    pinned_at = serializers.DateTimeField(allow_null=True)
    is_favorite = serializers.BooleanField()
    is_blocked = serializers.BooleanField()
    client_can_send_voice = serializers.BooleanField()
    tariff = ChatTariffSerializer(allow_null=True)

    class Meta:
        model = Chat
        fields = (
            'id',
            'companion',
            'channel_id',
            'created_at',
            'user_role',
            'last_access_order',
            'specialist_note',
            'latest_invite_delivery',
            'should_reply',
            'last_message',
            'last_message_at',
            'unread_count',
            'last_read_message_id',
            'companion_last_read_message_id',
            'pinned_at',
            'is_favorite',
            'is_blocked',
            'client_can_send_voice',
            'tariff',
        )


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
        # Отключаем авто-UniqueTogetherValidator:
        # если чат уже есть, вернем существующий через get_or_create в create().
        validators = []


class ChatUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Chat
        fields = ('specialist_note', 'client_can_send_voice')


class FavoriteChatRequestSerializer(serializers.Serializer):
    channel_id = serializers.CharField(max_length=255)


class PinChatRequestSerializer(serializers.Serializer):
    channel_id = serializers.CharField(max_length=255)


class SoftDeleteChatRequestSerializer(serializers.Serializer):
    channel_id = serializers.CharField(max_length=255)


class FavoriteChatSerializer(serializers.ModelSerializer):
    channel_id = serializers.CharField(source="chat.channel_id", read_only=True)

    class Meta:
        model = FavoriteChat
        fields = ("id", "channel_id", "created_at")


class BlockedChatSerializer(serializers.ModelSerializer):
    channel_id = serializers.CharField(source="chat.channel_id", read_only=True)

    class Meta:
        model = BlockedChat
        fields = ("id", "channel_id", "created_at")
