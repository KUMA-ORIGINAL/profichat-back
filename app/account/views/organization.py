from drf_spectacular.utils import extend_schema
from rest_framework import mixins, viewsets

from ..models import Organization
from ..serializers import OrganizationShortSerializer


@extend_schema(tags=['Organization'])
class OrganizationViewSet(viewsets.GenericViewSet, mixins.ListModelMixin):
    queryset = Organization.objects.filter(is_active=True).order_by('name')
    serializer_class = OrganizationShortSerializer
