from rest_framework import serializers

from ..models import WorkSchedule


class WorkScheduleListSerializer(serializers.ListSerializer):
    def create(self, validated_data):
        return WorkSchedule.objects.bulk_create([WorkSchedule(**item) for item in validated_data])


class WorkScheduleSerializer(serializers.ModelSerializer):
    user = serializers.HiddenField(default=serializers.CurrentUserDefault())

    class Meta:
        model = WorkSchedule
        fields = ('id', 'user', 'day_of_week', 'from_time', 'to_time', 'is_day_off', 'is_round_the_clock')
        list_serializer_class = WorkScheduleListSerializer

    def validate(self, attrs):
        is_day_off = attrs.get('is_day_off', False)
        is_round_the_clock = attrs.get('is_round_the_clock', False)

        if is_day_off and is_round_the_clock:
            raise serializers.ValidationError(
                "Нельзя одновременно указать выходной и круглосуточно."
            )

        if is_day_off or is_round_the_clock:
            attrs['from_time'] = None
            attrs['to_time'] = None
        else:
            if not attrs.get('from_time') or not attrs.get('to_time'):
                raise serializers.ValidationError(
                    "Укажите время начала и окончания, либо отметьте выходной/круглосуточно."
                )

        return attrs
