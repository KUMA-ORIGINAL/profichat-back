from rest_framework import serializers

from ..models import WorkSchedule


class WorkScheduleSerializer(serializers.ModelSerializer):
    user = serializers.HiddenField(default=serializers.CurrentUserDefault())

    class Meta:
        model = WorkSchedule
        fields = ('id', 'user', 'day_of_week', 'from_time', 'to_time')
