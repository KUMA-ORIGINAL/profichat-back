import django_filters
from drf_spectacular.utils import extend_schema_view, extend_schema, OpenApiParameter
from rest_framework import viewsets, permissions, mixins, status
from rest_framework import filters
from rest_framework.decorators import action
from rest_framework.response import Response
from django_filters.rest_framework import DjangoFilterBackend
from django.utils import timezone

from account.models import ROLE_SPECIALIST
from chat_access.models import AccessOrder
from chat_access.serializers import TariffSpecialistSerializer
from chat_access.serializers.specialist import CurrentClientTariffQuerySerializer, SpecialistAccessOrderSerializer
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

    @extend_schema(
        parameters=[OpenApiParameter(name="client_id", type=int, location=OpenApiParameter.QUERY, required=True)],
        summary="Получение текущего активного тарифа клиента",
    )
    @action(detail=False, methods=["get"], url_path="current-tariff")
    def current_tariff(self, request):
        if request.user.role != ROLE_SPECIALIST:
            return Response(
                {"detail": "Only specialists can view current client tariff."},
                status=status.HTTP_403_FORBIDDEN,
            )

        query_serializer = CurrentClientTariffQuerySerializer(data=request.query_params)
        query_serializer.is_valid(raise_exception=True)
        client_id = query_serializer.validated_data["client_id"]

        order = (
            AccessOrder.objects
            .filter(
                specialist=request.user,
                client_id=client_id,
                payment_status="success",
                expires_at__gt=timezone.now(),
            )
            .select_related("tariff")
            .order_by("-created_at", "-id")
            .first()
        )

        if order is None:
            return Response(
                {
                    "client_id": client_id,
                    "access_order_id": None,
                    "activated_at": None,
                    "expires_at": None,
                    "tariff": None,
                }
            )

        return Response(
            {
                "client_id": client_id,
                "access_order_id": order.id,
                "activated_at": order.activated_at,
                "expires_at": order.expires_at,
                "tariff": TariffSpecialistSerializer(order.tariff, context={"request": request}).data,
            }
        )
