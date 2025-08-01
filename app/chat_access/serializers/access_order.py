from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework import serializers

from account.models import ProfessionCategory
from ..models import AccessOrder, Chat

User = get_user_model()


class ProfessionCategorySerializer(serializers.ModelSerializer):

    class Meta:
        model = ProfessionCategory
        fields = ['id', 'name']  # Укажите нужные поля


class SpecialistSerializer(serializers.ModelSerializer):
    profession = ProfessionCategorySerializer(read_only=True)

    class Meta:
        model = User
        fields = ('id', 'first_name', 'last_name', 'profession', 'photo')


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
    channel_id = serializers.CharField(write_only=True)

    class Meta:
        model = AccessOrder
        fields = [
            'id',
            'client',
            'specialist',
            'tariff',
            'channel_id',
            'chat'
        ]
        read_only_fields = ['chat']  # Автоматически создаётся

    def validate(self, attrs):
        tariff = attrs.get('tariff')
        client = attrs.get('client')
        specialist = attrs.get('specialist')

        if tariff.tariff_type == 'free':
            # ищем существующий free-заказ у этого клиента/специалиста
            free_order = (
                AccessOrder.objects
                .filter(client=client, specialist=specialist, tariff__tariff_type='free')
                .first()
            )
            if free_order:
                # если он ещё активен — запрещаем
                if free_order.is_active:
                    raise serializers.ValidationError(
                        {'tariff': 'Ваш бесплатный тариф ещё активен.'}
                    )
                # если уже истёк — тоже запрещаем (только один free за всё время)
                else:
                    raise serializers.ValidationError(
                        {'tariff': 'Бесплатный тариф уже был использован для этого специалиста.'}
                    )

        return attrs

    def create(self, validated_data):
        channel_id = validated_data.pop('channel_id')
        client = validated_data['client']
        specialist = validated_data['specialist']

        chat, created = Chat.objects.get_or_create(
            client=client,
            specialist=specialist,
            defaults={'channel_id': channel_id}
        )

        if not created and chat.channel_id != channel_id:
            raise serializers.ValidationError({
                'channel_id': 'Чат уже существует с другим channel_id.'
            })

        validated_data['chat'] = chat

        tariff = validated_data['tariff']
        validated_data['duration_hours'] = tariff.duration_hours
        validated_data['tariff_type'] = tariff.tariff_type
        validated_data['price'] = tariff.price

        return super().create(validated_data)


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
