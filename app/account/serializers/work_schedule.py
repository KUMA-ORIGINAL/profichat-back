from rest_framework import serializers

from ..models import WorkSchedule


class WorkScheduleListSerializer(serializers.ListSerializer):
    def create(self, validated_data):
        return WorkSchedule.objects.bulk_create([WorkSchedule(**item) for item in validated_data])


class WorkScheduleSerializer(serializers.ModelSerializer):
    user = serializers.HiddenField(default=serializers.CurrentUserDefault())

    class Meta:
        model = WorkSchedule
        fields = ('id', 'user', 'day_of_week', 'from_time', 'to_time')
        list_serializer_class = WorkScheduleListSerializer
