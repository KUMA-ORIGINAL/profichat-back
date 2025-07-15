from rest_framework import serializers


class StreamSystemMessageSerializer(serializers.Serializer):
    channel_id = serializers.CharField(required=True)
    custom_type = serializers.CharField(required=True)
    text = serializers.CharField(required=False, allow_blank=True, allow_null=True)
