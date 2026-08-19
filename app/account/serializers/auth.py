from django.contrib.auth import authenticate
from rest_framework import serializers

from account.models import OTP
from common.errors import AppError, ErrorCode


class VerifyOTPSerializer(serializers.Serializer):
    phone_number = serializers.CharField()
    code = serializers.CharField()


class PhoneNumberSerializer(serializers.Serializer):
    phone_number = serializers.CharField()
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
    phone_number = serializers.CharField()
    code = serializers.CharField()
    new_password = serializers.CharField(write_only=True)
