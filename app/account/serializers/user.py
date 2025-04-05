from django.contrib.auth import authenticate
from rest_framework import serializers

from ..models import User, Application


class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ('id', 'phone_number', 'first_name', 'last_name', 'photo')


class UserMeSerializer(serializers.ModelSerializer):
    application_status = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ('id', 'phone_number', 'first_name', 'last_name', 'gender', 'birthdate', 'photo', 'role', 'application_status')

    def get_application_status(self, obj):
        last_application = Application.objects.filter(user=obj).order_by('-created_at').first()
        return last_application.status if last_application else None


class UserMeUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ('id', 'phone_number', 'first_name', 'last_name', 'gender', 'birthdate', 'photo')


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
