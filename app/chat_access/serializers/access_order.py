from rest_framework import serializers

from ..models import AccessOrder


class AccessOrderSerializer(serializers.ModelSerializer):
    tariff_name = serializers.ReadOnlyField(source='tariff.name')
    specialist_name = serializers.SerializerMethodField()
    is_active = serializers.BooleanField(read_only=True)

    class Meta:
        model = AccessOrder
        fields = [
            'id',
            'client',
            'specialist',
            'specialist_name',
            'tariff',
            'tariff_name',
            'tariff_type',
            'price',
            'payment_status',
            'created_at',
            'activated_at',
            'expires_at',
            'is_active',
        ]
        read_only_fields = (
            'created_at',
            'activated_at',
            'expires_at',
            'is_active',
            'tariff_name',
            'duration_hours',
            'specialist_name',
        )

    def get_specialist_name(self, obj):
        return obj.specialist.get_full_name() or obj.specialist.username
