from rest_framework import serializers


class StreamSystemMessageSerializer(serializers.Serializer):
    chat_id = serializers.IntegerField(required=True)
    custom_type = serializers.CharField(required=True)
    text = serializers.CharField(required=False, allow_blank=True, allow_null=True)
