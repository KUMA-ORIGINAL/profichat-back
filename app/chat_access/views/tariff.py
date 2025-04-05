from rest_framework import viewsets, permissions

from ..models import Tariff
from ..serializers import TariffSerializer


class TariffViewSet(viewsets.ModelViewSet):
    queryset = Tariff.objects.all()
    serializer_class = TariffSerializer
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]

    def perform_create(self, serializer):
        # Если нужно, автоматически указывать текущего специалиста
        serializer.save(specialist=self.request.user)