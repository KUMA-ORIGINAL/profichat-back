from drf_spectacular.utils import extend_schema_view, extend_schema, OpenApiParameter
from rest_framework import viewsets, permissions, mixins
from rest_framework import filters
from django_filters.rest_framework import DjangoFilterBackend

from chat_access.models import AccessOrder
from chat_access.serializers.specialist import SpecialistAccessOrderSerializer
from rest_framework.pagination import PageNumberPagination


class StandardResultsSetPagination(PageNumberPagination):
    page_size = 10  # кол-во элементов на странице по умолчанию
    page_size_query_param = 'page_size'
    max_page_size = 100


@extend_schema_view(
    list=extend_schema(
        parameters=[
            OpenApiParameter(name="payment_status", type=str, location=OpenApiParameter.QUERY),
            OpenApiParameter(name="tariff", type=int, location=OpenApiParameter.QUERY),
            OpenApiParameter(name="activated_at", type=str, location=OpenApiParameter.QUERY),
            OpenApiParameter(name="expires_at", type=str, location=OpenApiParameter.QUERY),
            OpenApiParameter(name="client", type=int, location=OpenApiParameter.QUERY),
        ],
        summary='Получение истории заказов специалиста'
    )
)
class SpecialistAccessOrderViewSet(viewsets.GenericViewSet,
                                   mixins.ListModelMixin,):
    """
    API для просмотра истории заказов специалиста с фильтрацией и пагинацией
    """
    serializer_class = SpecialistAccessOrderSerializer
    permission_classes = [permissions.IsAuthenticated]
    pagination_class = StandardResultsSetPagination

    filter_backends = [DjangoFilterBackend, filters.OrderingFilter, filters.SearchFilter]
    filterset_fields = ['payment_status', 'tariff', 'activated_at', 'expires_at', 'client']
    search_fields = ['client__username', 'client__first_name', 'client__last_name']
    ordering_fields = ['created_at', 'activated_at', 'expires_at', 'price']
    ordering = ['-created_at']  # сортировка по умолчанию

    def get_queryset(self):
        user = self.request.user
        return (
            AccessOrder.objects
            .filter(specialist=user)
            .select_related('client', 'specialist', 'tariff',)
            .order_by('-created_at')
        )