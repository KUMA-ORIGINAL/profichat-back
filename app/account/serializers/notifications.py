from rest_framework import serializers

class RegisterFCMTokenSerializer(serializers.Serializer):
    registration_id = serializers.CharField(help_text="FCM registration token")
