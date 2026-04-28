from rest_framework import serializers


class SecondSystemWebviewUrlRequestSerializer(serializers.Serializer):
    next = serializers.CharField(required=False, allow_blank=True, max_length=512)

    def validate_next(self, value):
        if not value:
            return "/"
        if not value.startswith("/") or value.startswith("//"):
            raise serializers.ValidationError("Must be a relative path starting with '/'.")
        return value


class SecondSystemWebviewUrlResponseSerializer(serializers.Serializer):
    url = serializers.URLField()


class VerifySecondSystemSSOTokenRequestSerializer(serializers.Serializer):
    token = serializers.CharField(required=True, allow_blank=False)


class VerifySecondSystemSSOTokenUserSerializer(serializers.Serializer):
    id = serializers.CharField()
    phone = serializers.CharField()
    role = serializers.CharField(allow_blank=True)
    first_name = serializers.CharField(allow_blank=True, allow_null=True)
    last_name = serializers.CharField(allow_blank=True, allow_null=True)


class VerifySecondSystemSSOTokenResponseSerializer(serializers.Serializer):
    valid = serializers.BooleanField()
    user = VerifySecondSystemSSOTokenUserSerializer(required=False)
    next = serializers.CharField(required=False)
