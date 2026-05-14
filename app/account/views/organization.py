from django.db.models import Prefetch
from drf_spectacular.utils import extend_schema
from rest_framework import mixins, viewsets
from rest_framework.decorators import action
from rest_framework.filters import SearchFilter
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from ..models import (
    Organization,
    OrganizationAddress,
    OrganizationWorkSchedule,
    OrganizationSocialLink,
    OrganizationService,
    OrganizationGalleryImage,
)
from ..models.user import User, ROLE_SPECIALIST
from ..serializers import OrganizationShortSerializer
from ..serializers.organization import OrganizationDetailSerializer, OrganizationMemberSerializer


class OrganizationPagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = 'page_size'
    max_page_size = 100


@extend_schema(tags=['Organization'])
class OrganizationViewSet(
    viewsets.GenericViewSet,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
):
    filter_backends = [SearchFilter]
    search_fields = ['name']
    permission_classes = [AllowAny]
    pagination_class = OrganizationPagination

    def get_queryset(self):
        if self.action == 'retrieve':
            return (
                Organization.objects
                .filter(is_active=True)
                .prefetch_related(
                    Prefetch('addresses', queryset=OrganizationAddress.objects.all()),
                    Prefetch('work_schedules', queryset=OrganizationWorkSchedule.objects.order_by('day_of_week')),
                    Prefetch('social_links', queryset=OrganizationSocialLink.objects.select_related('social_network')),
                    Prefetch('services', queryset=OrganizationService.objects.all()),
                    Prefetch('gallery_images', queryset=OrganizationGalleryImage.objects.order_by('order', 'id')),
                )
            )
        return Organization.objects.filter(is_active=True).order_by('name')

    def get_serializer_class(self):
        if self.action == 'retrieve':
            return OrganizationDetailSerializer
        return OrganizationShortSerializer

    @extend_schema(
        summary="Список специалистов организации",
        responses={200: OrganizationMemberSerializer(many=True)},
    )
    @action(detail=True, methods=['get'], url_path='specialists', permission_classes=[AllowAny])
    def specialists(self, request, pk=None):
        org = self.get_object()
        members = (
            User.objects
            .filter(organization=org, role=ROLE_SPECIALIST, is_active=True)
            .select_related('profession')
            .order_by('first_name', 'last_name')
        )
        serializer = OrganizationMemberSerializer(
            members, many=True, context=self.get_serializer_context()
        )
        return Response(serializer.data)
