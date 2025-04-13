from rest_framework import serializers

from ..models import Tariff


class TariffSpecialistSerializer(serializers.ModelSerializer):
    class Meta:
        model = Tariff
        fields = [
            'id',
            'name',
            'price',
            'duration_hours',
            'tariff_type',
        ]


class TariffSerializer(serializers.ModelSerializer):
    specialist = serializers.HiddenField(default=serializers.CurrentUserDefault())

    class Meta:
        model = Tariff
        fields = [
            'id',
            'name',
            'price',
            'duration_hours',
            'is_active',
            'tariff_type',
            'specialist',
        ]