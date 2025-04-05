from rest_framework import viewsets, permissions

from ..models import AccessOrder
from ..serializers import AccessOrderSerializer


class AccessOrderViewSet(viewsets.ModelViewSet):
    queryset = AccessOrder.objects.all()
    serializer_class = AccessOrderSerializer
    permission_classes = [permissions.IsAuthenticated]

    def perform_create(self, serializer):
        # При создании — указываем клиента
        serializer.save(client=self.request.user)