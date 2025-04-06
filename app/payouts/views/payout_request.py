from rest_framework import viewsets, permissions

from ..models import PayoutRequest
from ..serializers import PayoutRequestSerializer


class PayoutRequestViewSet(viewsets.ModelViewSet):
    serializer_class = PayoutRequestSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return PayoutRequest.objects.filter(user=self.request.user)

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)
