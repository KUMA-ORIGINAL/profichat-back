from rest_framework import serializers

from .profession_category import ProfessionCategoryMeSerializer
from .organization import OrganizationShortSerializer
from ..models import User, Application, Organization


class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ('id', 'phone_number', 'first_name', 'last_name', 'middle_name', 'photo')


class UserMeSerializer(serializers.ModelSerializer):
    application_status = serializers.SerializerMethodField()
    profession = ProfessionCategoryMeSerializer(read_only=True)
    organization = OrganizationShortSerializer(read_only=True)

    class Meta:
        model = User
        fields = ('id', 'phone_number', 'first_name', 'last_name', 'middle_name', 'gender', 'balance', 'birthdate', 'description',
                  'photo', 'role', 'application_status', 'show_in_search', 'invite_greeting',
                  'can_audio_call', 'can_video_call', 'education', 'work_experience', 'profession', 'organization')

    def get_application_status(self, obj):
        last_application = Application.objects.filter(user=obj).order_by('-created_at').first()
        return last_application.status if last_application else None


class UserMeUpdateSerializer(serializers.ModelSerializer):
    organization = serializers.PrimaryKeyRelatedField(
        queryset=Organization.objects.filter(is_active=True),
        required=False,
        allow_null=True,
    )

    class Meta:
        model = User
        fields = ('id', 'phone_number', 'first_name', 'last_name', 'middle_name', 'gender',
                  'birthdate', 'description', 'photo', 'education', 'work_experience', 'profession', 'organization')


class ShowInSearchSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ('show_in_search',)


class InviteGreetingSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ('invite_greeting',)


class CanCallSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ('can_audio_call', 'can_video_call')
