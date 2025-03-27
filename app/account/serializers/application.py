from rest_framework import serializers

from ..models import Application, WorkExperience


class WorkExperienceSerializer(serializers.ModelSerializer):
    class Meta:
        model = WorkExperience
        fields = ['name',]


class ApplicationSerializer(serializers.ModelSerializer):
    work_experiences = WorkExperienceSerializer(many=True)

    class Meta:
        model = Application
        fields = ['id', 'first_name', 'last_name', 'profession', 'education', 'work_experiences', 'created_at']

    def create(self, validated_data):
        work_experiences_data = validated_data.pop('work_experiences')

        application = Application.objects.create(**validated_data)

        for work_data in work_experiences_data:
            WorkExperience.objects.create(application=application, **work_data)

        return application
