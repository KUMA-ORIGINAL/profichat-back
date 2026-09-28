from datetime import timedelta

from django.utils import timezone
from rest_framework import serializers

from ..models import NonWorkingDate

# календарь в приложении позволяет выбирать даты не дальше чем на год вперёд
MAX_DAYS_AHEAD = 366
MAX_DATES_PER_SYNC = 100


def validate_non_working_date(value):
    today = timezone.localdate()
    if value < today:
        raise serializers.ValidationError("Нельзя отметить прошедшую дату.")
    if value > today + timedelta(days=MAX_DAYS_AHEAD):
        raise serializers.ValidationError("Дату можно отметить не дальше чем на год вперёд.")
    return value


class NonWorkingDateSerializer(serializers.ModelSerializer):
    date = serializers.DateField(validators=[validate_non_working_date])

    class Meta:
        model = NonWorkingDate
        fields = ('id', 'date')


class NonWorkingDateSyncSerializer(serializers.Serializer):
    dates = serializers.ListField(
        child=serializers.DateField(validators=[validate_non_working_date]),
        allow_empty=True,
        max_length=MAX_DATES_PER_SYNC,
    )

    def validate_dates(self, value):
        return sorted(set(value))
