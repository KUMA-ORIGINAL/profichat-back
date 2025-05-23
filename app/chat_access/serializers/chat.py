from rest_framework import serializers
from django.contrib.auth import get_user_model
from ..models import Chat

User = get_user_model()


class UserShortSerializer(serializers.ModelSerializer):
    """Краткий сериализатор пользователя (для отображения в чате)"""

    class Meta:
        model = User
        fields = ('id', 'username', 'email')  # Добавьте/уберите поля по необходимости


class ChatSerializer(serializers.ModelSerializer):
    client = UserShortSerializer(read_only=True)
    specialist = UserShortSerializer(read_only=True)

    class Meta:
        model = Chat
        fields = (
            'id',
            'client',
            'specialist',
            'channel_id',
            'created_at',
        )
        read_only_fields = ('id', 'created_at', 'channel_id')
