from rest_framework import serializers

from account.models import InviteDelivery
from chat_access.models import Tariff


class InviteClientSerializer(serializers.Serializer):
    phone_number = serializers.CharField()
    tariff_id = serializers.IntegerField()
    note = serializers.CharField(required=False, allow_blank=True, max_length=1000)

    def validate_tariff_id(self, value):
        if not Tariff.objects.filter(id=value).exists():
            raise serializers.ValidationError("Тариф не найден.")
        return value


class InviteDeliverySerializer(serializers.ModelSerializer):
    class Meta:
        model = InviteDelivery
        fields = (
            "id",
            "created_at",
            "channel",
            "status",
            "is_new_client",
            "provider_message_id",
            "provider_status",
            "error_message",
            "metadata",
        )


class InviteDeliveryListQuerySerializer(serializers.Serializer):
    chat_id = serializers.IntegerField(required=False)
    limit = serializers.IntegerField(required=False, min_value=1, max_value=50, default=20)
