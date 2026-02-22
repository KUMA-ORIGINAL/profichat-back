from rest_framework import serializers

from chat_access.models import Tariff


class MedCRMTariffSerializer(serializers.ModelSerializer):
    class Meta:
        model = Tariff
        fields = [
            "id",
            "name",
            "price",
            "duration_hours",
            "tariff_type",
            "is_active",
        ]


class MedCRMInviteClientSerializer(serializers.Serializer):
    specialist_phone_number = serializers.CharField(
        help_text="Номер телефона специалиста (в формате +996...)"
    )
    client_phone_number = serializers.CharField(
        help_text="Номер телефона клиента (в формате +996...)"
    )
    tariff_id = serializers.IntegerField(
        help_text="ID тарифа специалиста"
    )
    note = serializers.CharField(
        required=False, allow_blank=True, max_length=1000,
        help_text="Заметка специалиста о клиенте"
    )

    def validate_tariff_id(self, value):
        if not Tariff.objects.filter(id=value, is_archive=False).exists():
            raise serializers.ValidationError("Тариф не найден.")
        return value


class MedCRMInviteResponseSerializer(serializers.Serializer):
    chat_id = serializers.IntegerField()
    channel_id = serializers.CharField()
    client_id = serializers.IntegerField()
    is_new_client = serializers.BooleanField()
