from rest_framework import serializers


class ErkinAIPushSerializer(serializers.Serializer):
    """Запрос на доставку push-уведомления пользователю ProfiChat."""

    phone_number = serializers.CharField(
        max_length=32,
        help_text="Номер телефона получателя (в формате +996...)",
    )
    title = serializers.CharField(
        max_length=255,
        help_text="Заголовок уведомления",
    )
    body = serializers.CharField(
        max_length=4000,
        help_text="Текст уведомления",
    )
    payload = serializers.DictField(
        required=False,
        help_text=(
            "Доп. данные для приложения. Уходят в FCM data, "
            "поэтому значения приводятся к строкам."
        ),
    )
    external_id = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=128,
        help_text=(
            "Идентификатор отправки на стороне ErkinAI. Повторный запрос с тем же "
            "external_id не создаёт второе уведомление и не шлёт второй push."
        ),
    )

    def validate_phone_number(self, value):
        phone = value.strip()
        if not phone:
            raise serializers.ValidationError("Номер телефона обязателен.")
        return phone

    def validate_title(self, value):
        title = value.strip()
        if not title:
            raise serializers.ValidationError("Заголовок обязателен.")
        return title

    def validate_body(self, value):
        body = value.strip()
        if not body:
            raise serializers.ValidationError("Текст уведомления обязателен.")
        return body


class ErkinAIPushResponseSerializer(serializers.Serializer):
    """Что именно произошло с этой отправкой — целиком, без догадок."""

    notification_id = serializers.IntegerField()
    delivered = serializers.BooleanField(
        help_text="Push принят FCM хотя бы одним устройством.",
    )
    device_count = serializers.IntegerField(
        help_text="Сколько активных устройств было у пользователя.",
    )
    success_count = serializers.IntegerField()
    error_code = serializers.CharField(allow_blank=True)
    error_message = serializers.CharField(allow_blank=True)
    duplicate = serializers.BooleanField(
        help_text="Запрос отброшен как повтор по external_id.",
    )
