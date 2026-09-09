from rest_framework import serializers

from ..models import WorkSchedule


class WorkScheduleListSerializer(serializers.ListSerializer):
    def create(self, validated_data):
        return WorkSchedule.objects.bulk_create([WorkSchedule(**item) for item in validated_data])


class WorkScheduleSerializer(serializers.ModelSerializer):
    user = serializers.HiddenField(default=serializers.CurrentUserDefault())

    class Meta:
        model = WorkSchedule
        fields = (
            'id', 'user', 'day_of_week', 'from_time', 'to_time',
            'lunch_from_time', 'lunch_to_time', 'is_day_off', 'is_round_the_clock',
        )
        list_serializer_class = WorkScheduleListSerializer

    def validate(self, attrs):
        def value(field, default=None):
            if field in attrs:
                return attrs[field]
            return getattr(self.instance, field, default)

        is_day_off = value('is_day_off', False)
        is_round_the_clock = value('is_round_the_clock', False)

        if is_day_off and is_round_the_clock:
            raise serializers.ValidationError(
                "Нельзя одновременно указать выходной и круглосуточно."
            )

        if is_day_off or is_round_the_clock:
            attrs['from_time'] = None
            attrs['to_time'] = None
            attrs['lunch_from_time'] = None
            attrs['lunch_to_time'] = None
        else:
            from_time = value('from_time')
            to_time = value('to_time')
            lunch_from_time = value('lunch_from_time')
            lunch_to_time = value('lunch_to_time')

            if not from_time or not to_time:
                raise serializers.ValidationError(
                    "Укажите время начала и окончания, либо отметьте выходной/круглосуточно."
                )
            if from_time >= to_time:
                raise serializers.ValidationError(
                    "Время окончания работы должно быть позже времени начала."
                )
            if bool(lunch_from_time) != bool(lunch_to_time):
                raise serializers.ValidationError(
                    "Укажите время начала и окончания обеда."
                )
            if lunch_from_time and not (from_time < lunch_from_time < lunch_to_time < to_time):
                raise serializers.ValidationError(
                    "Обед должен находиться внутри рабочего времени."
                )

        return attrs
