from rest_framework import viewsets, permissions

from ..models import Tariff
from ..serializers import TariffSerializer


class TariffViewSet(viewsets.ModelViewSet):
    queryset = Tariff.objects.filter(is_active=True)
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]
    serializer_class = TariffSerializer

    def get_queryset(self):
        return Tariff.objects.filter(specialist=self.request.user)
