from django.contrib.auth import authenticate
from rest_framework import serializers


class VerifyOTPSerializer(serializers.Serializer):
    phone_number = serializers.CharField()
    code = serializers.CharField()


class PhoneNumberSerializer(serializers.Serializer):
    phone_number = serializers.CharField()


class VerifyOTPWithUserSerializer(serializers.Serializer):
    phone_number = serializers.CharField()
    code = serializers.CharField()
    password = serializers.CharField()
    first_name = serializers.CharField()
    last_name = serializers.CharField()


class LoginSerializer(serializers.Serializer):
    phone_number = serializers.CharField()
    password = serializers.CharField(write_only=True)

    def validate(self, data):
        user = authenticate(phone_number=data["phone_number"], password=data["password"])
        if not user:
            raise serializers.ValidationError("Неверный номер телефона или пароль!")
        if not user.is_active:
            raise serializers.ValidationError("Аккаунт не активирован")
        return {"user": user}


class PasswordResetConfirmSerializer(serializers.Serializer):
    phone_number = serializers.CharField()
    code = serializers.CharField()
    new_password = serializers.CharField(write_only=True)
