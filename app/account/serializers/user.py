from django.db import transaction
from rest_framework import serializers

from .profession_category import ProfessionCategoryMeSerializer
from .organization import OrganizationShortSerializer
from ..models import User, Application, Organization, UserEducation, UserWorkplace


class UserEducationSerializer(serializers.ModelSerializer):
    start_date = serializers.DateField(required=True)
    end_date = serializers.DateField(required=True)

    class Meta:
        model = UserEducation
        fields = ('id', 'institution', 'faculty', 'start_date', 'end_date')
        read_only_fields = ('id',)

    def validate(self, attrs):
        if attrs['end_date'] < attrs['start_date']:
            raise serializers.ValidationError({
                'end_date': 'Дата окончания не может быть раньше даты начала.'
            })
        return attrs


class UserWorkplaceSerializer(serializers.ModelSerializer):
    start_date = serializers.DateField(required=True)

    class Meta:
        model = UserWorkplace
        fields = ('id', 'organization', 'position', 'start_date', 'end_date', 'is_current')
        read_only_fields = ('id',)

    def validate(self, attrs):
        start_date = attrs['start_date']
        end_date = attrs.get('end_date')
        is_current = attrs.get('is_current', False)
        if is_current and end_date:
            raise serializers.ValidationError({
                'end_date': 'Для текущего места работы дата окончания должна быть пустой.'
            })
        if not is_current and not end_date:
            raise serializers.ValidationError({
                'end_date': 'Укажите дату окончания или отметьте, что работаете здесь сейчас.'
            })
        if end_date and end_date < start_date:
            raise serializers.ValidationError({
                'end_date': 'Дата окончания не может быть раньше даты начала.'
            })
        return attrs


class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ('id', 'phone_number', 'first_name', 'last_name', 'middle_name', 'photo')


class UserMeSerializer(serializers.ModelSerializer):
    application_status = serializers.SerializerMethodField()
    profession = ProfessionCategoryMeSerializer(read_only=True)
    organization = OrganizationShortSerializer(read_only=True)
    education = UserEducationSerializer(source='educations', many=True, read_only=True)
    work_experience = UserWorkplaceSerializer(source='workplaces', many=True, read_only=True)

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
    education = UserEducationSerializer(source='educations', many=True, required=False)
    work_experience = UserWorkplaceSerializer(source='workplaces', many=True, required=False)

    class Meta:
        model = User
        fields = ('id', 'phone_number', 'first_name', 'last_name', 'middle_name', 'gender',
                  'birthdate', 'description', 'photo', 'education', 'work_experience', 'profession', 'organization')

    @transaction.atomic
    def update(self, instance, validated_data):
        # Не меняем serializer.validated_data: view использует его после save(),
        # чтобы отправить список изменившихся полей по websocket.
        validated_data = validated_data.copy()
        educations = validated_data.pop('educations', None)
        workplaces = validated_data.pop('workplaces', None)
        instance = super().update(instance, validated_data)

        if educations is not None:
            instance.educations.all().delete()
            UserEducation.objects.bulk_create(
                UserEducation(user=instance, **item) for item in educations
            )

        if workplaces is not None:
            instance.workplaces.all().delete()
            UserWorkplace.objects.bulk_create(
                UserWorkplace(user=instance, **item) for item in workplaces
            )

        return instance


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
