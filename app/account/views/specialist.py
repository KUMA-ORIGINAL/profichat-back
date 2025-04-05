from django.db.models import Prefetch
from drf_spectacular.utils import extend_schema
from rest_framework import viewsets
from rest_framework.filters import SearchFilter
from rest_framework.permissions import AllowAny
from django_filters.rest_framework import DjangoFilterBackend

from chat_access.models import Tariff
from ..models import User
from ..serializers import SpecialistListSerializer, SpecialistSerializer


@extend_schema(tags=['Specialist'])
class SpecialistViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = User.objects.filter(role='specialist').prefetch_related(
        Prefetch('tariffs', queryset=Tariff.objects.filter(is_active=True))
    )
    permission_classes = [AllowAny]
    filter_backends = [DjangoFilterBackend, SearchFilter]
    filterset_fields = ['profession']
    search_fields = ['first_name', 'last_name']

    def get_serializer_class(self):
        if self.action == 'list':
            return SpecialistListSerializer
        return SpecialistSerializer
