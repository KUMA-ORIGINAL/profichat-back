from rest_framework import serializers
from ..models import Notification

class RegisterFCMTokenSerializer(serializers.Serializer):
    registration_id = serializers.CharField(help_text="FCM registration token")


class NotificationSerializer(serializers.ModelSerializer):
    source = serializers.CharField(
        read_only=True,
        help_text=(
            "Кто породил уведомление: `profichat` — само приложение, "
            "`erkinai` — внешняя CRM."
        ),
    )

    class Meta:
        model = Notification
        fields = (
            "id",
            "source",
            "notification_type",
            "title",
            "message",
            "payload",
            "is_read",
            "read_at",
            "created_at",
        )


class NotificationReadSerializer(serializers.Serializer):
    notification_ids = serializers.ListField(
        child=serializers.IntegerField(min_value=1),
        allow_empty=False,
        help_text="Список id уведомлений для отметки как прочитанные",
    )
