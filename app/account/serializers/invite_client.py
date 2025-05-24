from rest_framework import serializers

from chat_access.models import Tariff


class InviteClientSerializer(serializers.Serializer):
    phone_number = serializers.CharField()
    tariff_id = serializers.IntegerField()

    def validate_tariff_id(self, value):
        if not Tariff.objects.filter(id=value).exists():
            raise serializers.ValidationError("Тариф не найден.")
        return value
