from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from chat_access.models import Chat
from chat_access.serializers import TariffSpecialistSerializer
from .organization import OrganizationShortSerializer
from .profession_category import ProfessionCategorySerializer
from .work_schedule import WorkScheduleSerializer
from .non_working_date import NonWorkingDateSerializer
from .user import UserEducationSerializer, UserWorkplaceSerializer

from ..models import User


class SpecialistSerializer(serializers.ModelSerializer):
    profession = ProfessionCategorySerializer(read_only=True)
    tariffs = TariffSpecialistSerializer(many=True, read_only=True)
    channel_id = serializers.SerializerMethodField()
    work_schedules = WorkScheduleSerializer(many=True, read_only=True)
    non_working_dates = serializers.SerializerMethodField()
    organization = OrganizationShortSerializer(read_only=True)
    education = UserEducationSerializer(source='educations', many=True, read_only=True)
    work_experience = UserWorkplaceSerializer(source='workplaces', many=True, read_only=True)

    class Meta:
        model = User
        fields = ["id", "first_name", "last_name", 'middle_name', "phone_number", "photo",
                  'description', 'rating', 'can_audio_call', 'can_video_call', 'education', 'work_experience', "profession", 'channel_id', 'tariffs', 'work_schedules', 'non_working_dates', 'organization']

    @extend_schema_field(NonWorkingDateSerializer(many=True))
    def get_non_working_dates(self, obj):
        # только предстоящие даты — прошедшие клиенту не нужны
        return NonWorkingDateSerializer(obj.non_working_dates.upcoming(), many=True).data

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
    education = UserEducationSerializer(source='educations', many=True, read_only=True)
    work_experience = UserWorkplaceSerializer(source='workplaces', many=True, read_only=True)

    class Meta:
        model = User
        fields = ["id", "first_name", "last_name", 'middle_name', "phone_number", "photo", 'rating', 'education', 'work_experience', "profession"]
