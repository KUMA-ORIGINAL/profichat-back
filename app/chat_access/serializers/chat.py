from rest_framework import serializers
from django.contrib.auth import get_user_model

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


class ChatListSerializer(serializers.ModelSerializer):
    companion = UserShortSerializer()
    user_role = serializers.CharField()
    last_access_order = AccessOrderShortSerializer(allow_null=True)
    specialist_note = serializers.CharField(allow_null=True)
    latest_invite_delivery = serializers.DictField(allow_null=True)
    should_reply = serializers.BooleanField()

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
