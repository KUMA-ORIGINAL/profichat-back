from django.contrib.auth import authenticate
from rest_framework import serializers


class RegisterSerializer(serializers.Serializer):
    phone_number = serializers.CharField()
    password = serializers.CharField(write_only=True)
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


class PasswordResetRequestSerializer(serializers.Serializer):
    phone_number = serializers.CharField()


class PasswordResetConfirmSerializer(serializers.Serializer):
    phone_number = serializers.CharField()
    code = serializers.CharField()
    new_password = serializers.CharField(write_only=True)
