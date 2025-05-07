from rest_framework import serializers

from chat_access.serializers import TariffSpecialistSerializer
from .profession_category import ProfessionCategorySerializer

from ..models import User


class SpecialistSerializer(serializers.ModelSerializer):
    profession = ProfessionCategorySerializer(read_only=True)
    tariffs = TariffSpecialistSerializer(many=True, read_only=True)

    class Meta:
        model = User
        fields = ["id", "first_name", "last_name", "phone_number", "photo", "profession", 'description', 'tariffs']


class SpecialistListSerializer(serializers.ModelSerializer):
    profession = ProfessionCategorySerializer(read_only=True)

    class Meta:
        model = User
        fields = ["id", "first_name", "last_name", "phone_number", "photo", "profession"]
