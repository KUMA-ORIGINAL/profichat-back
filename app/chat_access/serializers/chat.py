from django.utils import timezone
from rest_framework import serializers
from django.contrib.auth import get_user_model
from ..models import Chat

User = get_user_model()


class UserShortSerializer(serializers.ModelSerializer):
    """Краткий сериализатор пользователя (для отображения в чате)"""

    class Meta:
        model = User
        fields = ('id', 'first_name', 'last_name', 'photo')


class ChatListSerializer(serializers.ModelSerializer):
    companion = serializers.SerializerMethodField()
    user_role = serializers.SerializerMethodField()
    access_status = serializers.SerializerMethodField()

    class Meta:
        model = Chat
        fields = (
            'id',
            'companion',
            'channel_id',
            'created_at',
            'user_role',
            'access_status'
        )

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

    def get_access_status(self, obj):
        user = self.context['request'].user
        if obj.client != user:
            return None

        now = timezone.now()
        active_orders = obj.access_orders.filter(
            client=user,
            payment_status='success',
            expires_at__gt=now
        )
        return "active" if active_orders.exists() else "inactive"


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
