from drf_spectacular.utils import extend_schema
from rest_framework import viewsets
from rest_framework.permissions import AllowAny
from django_filters.rest_framework import DjangoFilterBackend

from ..models import User
from ..serializers import SpecialistSerializer


@extend_schema(tags=['Specialist'])
class SpecialistViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = User.objects.filter(role='specialist')  # Только специалисты
    serializer_class = SpecialistSerializer
    permission_classes = [AllowAny]
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ['profession']  # Фильтрация по категории специальности
