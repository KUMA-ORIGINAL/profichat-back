from rest_framework import viewsets, permissions

from ..models import AccessOrder
from ..serializers import AccessOrderSerializer


class AccessOrderViewSet(viewsets.ModelViewSet):
    serializer_class = AccessOrderSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return AccessOrder.objects.filter(client=self.request.user)