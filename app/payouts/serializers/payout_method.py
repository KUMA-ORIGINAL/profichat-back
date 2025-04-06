from rest_framework import serializers

from ..models import PayoutMethod


class PayoutMethodSerializer(serializers.ModelSerializer):
    class Meta:
        model = PayoutMethod
        fields = ['id', 'name']
