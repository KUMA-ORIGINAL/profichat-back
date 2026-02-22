from django.db.models import Prefetch
from drf_spectacular.utils import extend_schema
from rest_framework import viewsets, permissions
from rest_framework.filters import SearchFilter
from rest_framework.pagination import PageNumberPagination
from django_filters.rest_framework import DjangoFilterBackend

from chat_access.models import Tariff
from ..filters import SpecialistFilter
from ..models import User
from ..serializers import SpecialistListSerializer, SpecialistSerializer


class SpecialistPagination(PageNumberPagination):
    page_size = 10
    page_size_query_param = 'page_size'
    max_page_size = 100


@extend_schema(tags=['Specialist'])
class SpecialistViewSet(viewsets.ReadOnlyModelViewSet):
    filter_backends = [DjangoFilterBackend, SearchFilter]
    filterset_class = SpecialistFilter
    search_fields = ['first_name', 'last_name']
    pagination_class = SpecialistPagination

    def get_queryset(self):
        base_qs = User.objects.filter(
            role='specialist',
            is_active=True
        ).prefetch_related(
            Prefetch(
                'tariffs',
                queryset=Tariff.objects.filter(is_active=True, is_archive=False)
            )
        )

        # только для списка применяем show_in_search
        if self.action == 'list':
            return base_qs.filter(show_in_search=True)

        return base_qs

    def get_serializer_class(self):
        if self.action == 'list':
            return SpecialistListSerializer
        return SpecialistSerializer

    def get_permissions(self):
        if self.action == 'list':
            return [permissions.AllowAny()]
        return [permissions.IsAuthenticated()]