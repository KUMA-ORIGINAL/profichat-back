from django.contrib.auth import authenticate
from rest_framework import serializers

from .profession_category import ProfessionCategoryMeSerializer
from ..models import User, Application


class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ('id', 'phone_number', 'first_name', 'last_name', 'photo')


class UserMeSerializer(serializers.ModelSerializer):
    application_status = serializers.SerializerMethodField()
    profession = ProfessionCategoryMeSerializer(read_only=True)

    class Meta:
        model = User
        fields = ('id', 'phone_number', 'first_name', 'last_name', 'gender', 'balance', 'birthdate', 'description',
                  'photo', 'role', 'application_status', 'show_in_search', 'profession')

    def get_application_status(self, obj):
        last_application = Application.objects.filter(user=obj).order_by('-created_at').first()
        return last_application.status if last_application else None


class UserMeUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ('id', 'phone_number', 'first_name', 'last_name', 'gender', 'birthdate', 'description', 'photo')


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


class ShowInSearchSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ('show_in_search',)
