from rest_framework import serializers

from messenger.models import Call


class CallSerializer(serializers.ModelSerializer):
    """Звонок: в ответах API, событиях `call.*` и в сообщениях `type=call`."""

    channel_id = serializers.CharField(source="chat.channel_id", read_only=True)
    caller_id = serializers.IntegerField(read_only=True)
    callee_id = serializers.IntegerField(read_only=True)

    class Meta:
        model = Call
        fields = (
            "id",
            "channel_id",
            "caller_id",
            "callee_id",
            "kind",
            "status",
            "created_at",
            "answered_at",
            "ended_at",
            "duration_seconds",
            "end_reason",
        )
        read_only_fields = fields
