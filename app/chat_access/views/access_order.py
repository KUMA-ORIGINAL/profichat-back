from rest_framework import viewsets, permissions, status
from rest_framework.decorators import action
from rest_framework.response import Response

from ..models import AccessOrder
from ..serializers import AccessOrderSerializer, ClientAccessSerializer, AccessOrderCreateSerializer
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

    @action(detail=False, methods=["get"], url_path="last-for-specialist/(?P<specialist_id>[^/.]+)")
    def last_for_specialist(self, request, specialist_id=None):
        try:
            order = AccessOrder.objects.filter(
                client=request.user,
                specialist_id=specialist_id
            ).order_by("-id").first()
            if order is None:
                return Response({"detail": "Заказ не найден."}, status=status.HTTP_404_NOT_FOUND)
            serializer = self.get_serializer(order)
            return Response(serializer.data)
        except Exception as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=False, methods=["get"], url_path="my-clients")
    def my_clients(self, request):
        user = request.user

        if not hasattr(user, 'role') or user.role != 'specialist':
            return Response({"detail": "Только специалист может просматривать клиентов."}, status=403)

        # Получаем последние заказы от каждого клиента к специалисту
        orders = (
            AccessOrder.objects
            .filter(specialist=user)
            .select_related('client', 'tariff')
            .order_by('client_id', '-created_at')
        )

        # Последний заказ каждого клиента
        latest_orders = {}
        for order in orders:
            if order.client_id not in latest_orders:
                latest_orders[order.client_id] = order

        serializer = ClientAccessSerializer(latest_orders.values(), many=True, context={"request": request})
        return Response(serializer.data)

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        access_order = serializer.save()

        payment_url = generate_payment_link(access_order)

        if not payment_url:
            return Response(
                {"detail": "Не удалось создать платёжную ссылку."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

        return Response({"payment_url": payment_url}, status=status.HTTP_201_CREATED)