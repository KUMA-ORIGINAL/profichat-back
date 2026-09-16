from rest_framework import serializers

from ..models import Application, ApplicationEducation, WorkExperience, Organization
from ..services.profession_request import create_application_request


class ApplicationEducationSerializer(serializers.ModelSerializer):
    start_date = serializers.DateField(required=True)
    end_date = serializers.DateField(required=True)

    class Meta:
        model = ApplicationEducation
        fields = ['institution', 'faculty', 'start_date', 'end_date']

    def validate(self, attrs):
        if attrs['end_date'] < attrs['start_date']:
            raise serializers.ValidationError({'end_date': 'Дата окончания не может быть раньше даты начала.'})
        return attrs


class WorkExperienceSerializer(serializers.ModelSerializer):
    start_date = serializers.DateField(required=True)

    class Meta:
        model = WorkExperience
        fields = ['organization', 'position', 'start_date', 'end_date', 'is_current']

    def validate(self, attrs):
        start_date = attrs['start_date']
        end_date = attrs.get('end_date')
        is_current = attrs.get('is_current', False)
        if is_current and end_date:
            raise serializers.ValidationError({'end_date': 'Для текущего места работы дата окончания должна быть пустой.'})
        if not is_current and not end_date:
            raise serializers.ValidationError({'end_date': 'Укажите дату окончания или отметьте, что работаете здесь сейчас.'})
        if end_date and end_date < start_date:
            raise serializers.ValidationError({'end_date': 'Дата окончания не может быть раньше даты начала.'})
        return attrs


class ApplicationSerializer(serializers.ModelSerializer):
    user = serializers.HiddenField(default=serializers.CurrentUserDefault())
    work_experiences = WorkExperienceSerializer(many=True)
    education = ApplicationEducationSerializer(source='educations', many=True)
    organization = serializers.PrimaryKeyRelatedField(
        queryset=Organization.objects.filter(is_active=True),
        required=False,
        allow_null=True,
    )
    custom_profession_description = serializers.CharField(
        max_length=500,
        required=False,
        allow_blank=True,
        allow_null=True,
        error_messages={'max_length': 'Описание — не длиннее 500 символов.'},
    )

    class Meta:
        model = Application
        fields = [
            'id',
            'user',
            'first_name',
            'last_name',
            'profession',
            'organization',
            'custom_profession',
            'custom_profession_description',
            'custom_organization',
            'education',
            'work_experiences',
            'created_at',
        ]

    def validate(self, attrs):
        profession = attrs.get('profession')
        custom_profession = (attrs.get('custom_profession') or '').strip()

        if not profession and not custom_profession:
            raise serializers.ValidationError({
                "profession": "Выберите профессию из списка или укажите свой вариант."
            })

        if custom_profession:
            attrs['custom_profession'] = custom_profession

        # Описание имеет смысл только вместе со своей профессией; старые сборки его не шлют.
        description = (attrs.get('custom_profession_description') or '').strip()
        attrs['custom_profession_description'] = description if custom_profession else ''

        custom_organization = (attrs.get('custom_organization') or '').strip()
        if custom_organization:
            attrs['custom_organization'] = custom_organization

        return attrs

    def create(self, validated_data):
        work_experiences_data = validated_data.pop('work_experiences')
        educations_data = validated_data.pop('educations')

        application = Application.objects.create(**validated_data)

        for education_data in educations_data:
            ApplicationEducation.objects.create(application=application, **education_data)

        for work_data in work_experiences_data:
            WorkExperience.objects.create(application=application, **work_data)

        # Своя профессия попадает в общую очередь заявок на профессии
        if application.custom_profession:
            create_application_request(application)

        # Отправляем уведомление в Telegram о новой заявке на специалиста
        from common.telegram_notifier import notify_specialist_application
        import logging
        logger = logging.getLogger(__name__)
        
        try:
            notify_specialist_application(application)
        except Exception as e:
            logger.error(f"Failed to send Telegram notification for application {application.id}: {str(e)}")

        return application

