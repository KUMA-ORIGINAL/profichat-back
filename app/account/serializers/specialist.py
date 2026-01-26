from rest_framework import serializers

from chat_access.models import Chat
from chat_access.serializers import TariffSpecialistSerializer
from .profession_category import ProfessionCategorySerializer
from .work_schedule import WorkScheduleSerializer

from ..models import User


class SpecialistSerializer(serializers.ModelSerializer):
    profession = ProfessionCategorySerializer(read_only=True)
    tariffs = TariffSpecialistSerializer(many=True, read_only=True)
    channel_id = serializers.SerializerMethodField()
    work_schedules = WorkScheduleSerializer(many=True, read_only=True)

    class Meta:
        model = User
        fields = ["id", "first_name", "last_name", 'middle_name', "phone_number", "photo",
                  'description', 'can_audio_call', 'can_video_call', 'education', 'work_experience', "profession", 'channel_id', 'tariffs', 'work_schedules']

    def get_channel_id(self, obj):
        request = self.context.get('request')
        if not request or not request.user.is_authenticated:
            return None
        try:
            chat = Chat.objects.get(client=request.user, specialist=obj)
            return chat.channel_id
        except Chat.DoesNotExist:
            return None


class SpecialistListSerializer(serializers.ModelSerializer):
    profession = ProfessionCategorySerializer(read_only=True)

    class Meta:
        model = User
        fields = ["id", "first_name", "last_name", 'middle_name', "phone_number", "photo", 'education', 'work_experience', "profession"]
