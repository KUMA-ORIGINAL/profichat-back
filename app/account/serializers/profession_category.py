from rest_framework import serializers

from ..models import ProfessionCategory


class ProfessionCategorySerializer(serializers.ModelSerializer):
    subcategories = serializers.SerializerMethodField()

    class Meta:
        model = ProfessionCategory
        fields = ("id", "name", 'photo', 'subcategories')

    def get_subcategories(self, instance):
        # Получаем все подкатегории
        subcategories = instance.subcategories.all()
        if subcategories.exists():
            return ProfessionCategorySerializer(subcategories, many=True).data
        return []
