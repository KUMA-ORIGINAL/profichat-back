from django.utils import timezone
from rest_framework import viewsets, permissions, status
from rest_framework.decorators import action
from rest_framework.response import Response

from ..models import AccessOrder
from ..serializers.access_order import AccessOrderSerializer, ClientAccessSerializer, AccessOrderCreateSerializer, \
    SpecialistSerializer
from ..services.open_banking import generate_payment_link


class AccessOrderViewSet(viewsets.ModelViewSet):
    serializer_class = AccessOrderSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_serializer_class(self):
        if self.action == 'my_clients':
            return ClientAccessSerializer
        elif self.action == 'create':
            return AccessOrderCreateSerializer
        return AccessOrderSerializer

    def get_queryset(self):
        return AccessOrder.objects.filter(client=self.request.user)

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        access_order = serializer.save()

        specialist_data = SpecialistSerializer(access_order.specialist).data

        if access_order.tariff_type == 'free':
            access_order.payment_status = 'success'
            access_order.activate()  # Активируем доступ

            return Response({
                'id': access_order.id,
                'message': 'Доступ активирован сразу, так как выбран бесплатный тариф.'
            }, status=status.HTTP_201_CREATED)

        payment_url = generate_payment_link(access_order)
        if not payment_url:
            return Response(
                {"detail": "Failed to generate payment link. Please try again later."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

        data = {
            'id': access_order.id,
            "payment_url": payment_url,
            'specialist': specialist_data
        }
        return Response(data, status=status.HTTP_201_CREATED)

    @action(detail=False, methods=["get"], url_path="last-for-specialist/(?P<specialist_id>[^/.]+)")
    def last_for_specialist(self, request, specialist_id=None):
        try:
            now = timezone.now()
            order = AccessOrder.objects.filter(
                client=request.user,
                specialist_id=specialist_id,
                payment_status='success',
                expires_at__gt=now
            ).order_by('-id').first()

            if order is None:
                return Response(
                    {"detail": "No access order found for this specialist."},
                    status=status.HTTP_404_NOT_FOUND
                )

            serializer = self.get_serializer(order, context={"request": request})
            return Response(serializer.data)

        except Exception as e:
            return Response(
                {"detail": f"An error occurred while retrieving the access order: {str(e)}"},
                status=status.HTTP_400_BAD_REQUEST
            )

    @action(detail=False, methods=["get"], url_path="my-clients")
    def my_clients(self, request):
        user = request.user

        if not hasattr(user, 'role') or user.role != 'specialist':
            return Response(
                {"detail": "Only specialists can view clients."},
                status=status.HTTP_403_FORBIDDEN
            )

        orders = (
            AccessOrder.objects
            .filter(specialist=user)
            .select_related('client', 'tariff')
            .order_by( '-created_at')
        )

        latest_orders = {}
        for order in orders:
            if order.client_id not in latest_orders:
                latest_orders[order.client_id] = order

        serializer = ClientAccessSerializer(
            latest_orders.values(),
            many=True,
            context={"request": request}
        )
        return Response(serializer.data)
