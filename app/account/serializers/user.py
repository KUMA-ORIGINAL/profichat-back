from django.contrib.auth import authenticate
from rest_framework import serializers

from .profession_category import ProfessionCategorySerializer
from ..models import User


class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ('id', 'phone_number', 'first_name', 'last_name', 'photo')


class UserMeSerializer(serializers.ModelSerializer):

    class Meta:
        model = User
        fields = ('id', 'phone_number', 'first_name', 'last_name', 'photo')


class UserMeUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ('id', 'phone_number', 'first_name', 'last_name', 'photo')


class SpecialistSerializer(serializers.ModelSerializer):
    profession = ProfessionCategorySerializer(read_only=True)

    class Meta:
        model = User
        fields = ["id", "first_name", "last_name", "phone_number", "photo", "profession"]


class RegisterSerializer(serializers.Serializer):
    phone_number = serializers.CharField()
    password = serializers.CharField(write_only=True)


class LoginSerializer(serializers.Serializer):
    phone_number = serializers.CharField()
    password = serializers.CharField(write_only=True)

    def validate(self, data):
        user = authenticate(phone_number=data["phone_number"], password=data["password"])
        if not user:
            raise serializers.ValidationError("Неверный номер телефона или пароль!")
        return {"user": user}
