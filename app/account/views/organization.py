from drf_spectacular.utils import extend_schema
from rest_framework import mixins, viewsets
from rest_framework.filters import SearchFilter
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import AllowAny

from ..models import Organization
from ..serializers import OrganizationShortSerializer


class OrganizationPagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = 'page_size'
    max_page_size = 100


@extend_schema(tags=['Organization'])
class OrganizationViewSet(viewsets.GenericViewSet, mixins.ListModelMixin):
    queryset = Organization.objects.filter(is_active=True).order_by('name')
    serializer_class = OrganizationShortSerializer
    pagination_class = OrganizationPagination
    filter_backends = [SearchFilter]
    search_fields = ['name']
    permission_classes = [AllowAny]
