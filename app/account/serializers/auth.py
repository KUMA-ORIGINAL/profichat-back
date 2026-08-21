import phonenumbers
from django.contrib.auth import authenticate
from phonenumbers import NumberParseException
from rest_framework import serializers

from account.models import OTP
from common.errors import AppError, ErrorCode

# Совпадает с region у User.phone_number, чтобы локальный формат (0772…)
# и E.164 (+996772…) приводились к одному значению.
PHONE_REGION = "KG"


class PhoneNumberCharField(serializers.CharField):
    """Номер телефона, нормализованный в E.164.

    Раньше здесь был голый CharField, и до провайдера доходило что угодно —
    например, один код страны `+996`: запись OTP создавалась, провайдер
    отвечал 422, а клиент получал 500. Проверяем номер до похода в БД.
    """

    default_error_messages = {
        "invalid_phone": "Некорректный номер телефона",
    }

    def to_internal_value(self, data):
        value = super().to_internal_value(data)
        try:
            parsed = phonenumbers.parse(value, PHONE_REGION)
        except NumberParseException:
            self.fail("invalid_phone")
        if not phonenumbers.is_valid_number(parsed):
            self.fail("invalid_phone")
        return phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)


class VerifyOTPSerializer(serializers.Serializer):
    phone_number = PhoneNumberCharField()
    code = serializers.CharField()


class PhoneNumberSerializer(serializers.Serializer):
    phone_number = PhoneNumberCharField()
    app_signature = serializers.CharField(required=False, allow_blank=True, default="")
    channel = serializers.ChoiceField(
        choices=OTP.CHANNEL_CHOICES,
        required=False,
        default=OTP.CHANNEL_WHATSAPP,
        help_text="Канал доставки кода: whatsapp (по умолчанию) или sms — если код не пришёл.",
    )


class LoginSerializer(serializers.Serializer):
    phone_number = serializers.CharField()
    password = serializers.CharField(write_only=True)

    def validate(self, data):
        user = authenticate(phone_number=data["phone_number"], password=data["password"])
        if not user:
            raise AppError(
                "Неверный номер телефона или пароль!",
                code=ErrorCode.INVALID_CREDENTIALS,
            )
        if not user.is_active:
            raise AppError(
                "Аккаунт не активирован",
                code=ErrorCode.ACCOUNT_NOT_ACTIVATED,
            )
        return {"user": user}


class PasswordResetConfirmSerializer(serializers.Serializer):
    phone_number = PhoneNumberCharField()
    code = serializers.CharField()
    new_password = serializers.CharField(write_only=True)
