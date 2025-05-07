from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework import serializers

from ..models import AccessOrder

User = get_user_model()


class ClientAccessSerializer(serializers.Serializer):
    id = serializers.IntegerField(source='client.id')
    full_name = serializers.SerializerMethodField()
    photo = serializers.SerializerMethodField()
    tariff_duration = serializers.SerializerMethodField()
    time_left = serializers.SerializerMethodField()

    def get_full_name(self, obj):
        return f"{obj.client.first_name} {obj.client.last_name}"

    def get_photo(self, obj):
        request = self.context.get('request')
        photo = getattr(obj.client, 'photo', None)
        if photo and hasattr(photo, 'url'):
            if request:
                return request.build_absolute_uri(photo.url)
            return photo.url
        return None

    def get_tariff_duration(self, obj):
        return f"{obj.tariff.duration_hours} часа" if obj.tariff else ""

    def get_time_left(self, obj):
        if obj.expires_at and obj.expires_at > timezone.now():
            delta = obj.expires_at - timezone.now()
            hours = int(delta.total_seconds() // 3600)
            if hours == 1:
                return "1 час"
            return f"{hours} часа"
        return "0 часов"


class AccessOrderCreateSerializer(serializers.ModelSerializer):
    client = serializers.HiddenField(default=serializers.CurrentUserDefault())

    class Meta:
        model = AccessOrder
        fields = [
            'id',
            'client',
            'specialist',
            'tariff',
        ]


class AccessOrderSerializer(serializers.ModelSerializer):
    client = serializers.HiddenField(default=serializers.CurrentUserDefault())
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
            'duration_hours',
            'specialist_name',
        )

    def get_specialist_name(self, obj):
        return obj.specialist.get_full_name() or obj.specialist.username
