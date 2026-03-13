from rest_framework import serializers

from ..models import Application, WorkExperience, Organization


class WorkExperienceSerializer(serializers.ModelSerializer):
    class Meta:
        model = WorkExperience
        fields = ['name',]


class ApplicationSerializer(serializers.ModelSerializer):
    user = serializers.HiddenField(default=serializers.CurrentUserDefault())
    work_experiences = WorkExperienceSerializer(many=True)
    organization = serializers.PrimaryKeyRelatedField(
        queryset=Organization.objects.filter(is_active=True),
        required=False,
        allow_null=True,
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

        return attrs

    def create(self, validated_data):
        work_experiences_data = validated_data.pop('work_experiences')

        application = Application.objects.create(**validated_data)

        for work_data in work_experiences_data:
            WorkExperience.objects.create(application=application, **work_data)

        # Отправляем уведомление в Telegram о новой заявке на специалиста
        from common.telegram_notifier import notify_specialist_application
        import logging
        logger = logging.getLogger(__name__)
        
        try:
            notify_specialist_application(application)
        except Exception as e:
            logger.error(f"Failed to send Telegram notification for application {application.id}: {str(e)}")

        return application

