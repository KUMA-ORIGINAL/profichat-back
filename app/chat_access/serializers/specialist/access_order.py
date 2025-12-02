from rest_framework import serializers

from account.serializers import UserSerializer
from chat_access.models import AccessOrder

from chat_access.serializers import TariffSpecialistSerializer, ChatListSerializer


class SpecialistAccessOrderSerializer(serializers.ModelSerializer):
    client = UserSerializer(read_only=True)
    specialist = UserSerializer(read_only=True)
    tariff = TariffSpecialistSerializer(read_only=True)

    class Meta:
        model = AccessOrder
        fields = [
            'id',
            'client',
            'specialist',
            'tariff',
            'tariff_type',
            'price',
            'payment_status',
            'duration_hours',
            'created_at',
            'activated_at',
            'expires_at',
            'is_active',
        ]
