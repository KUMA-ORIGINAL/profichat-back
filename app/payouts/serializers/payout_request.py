from rest_framework import serializers

from ..models import PayoutRequest


class PayoutRequestSerializer(serializers.ModelSerializer):

    class Meta:
        model = PayoutRequest
        fields = [
            'id',
            'user',
            'method',
            'method_id',
            'phone_number',
            'amount',
            'status',
            'manager_comment',
            'created_at',
            'processed_at',
        ]
        read_only_fields = ['id', 'user', 'status', 'manager_comment', 'created_at', 'processed_at']