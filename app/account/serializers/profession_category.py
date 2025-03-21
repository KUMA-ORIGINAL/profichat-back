from rest_framework import serializers

from ..models import ProfessionCategory


class ProfessionCategorySerializer(serializers.ModelSerializer):

    class Meta:
        model = ProfessionCategory
        fields = ("id", "name", 'photo')
