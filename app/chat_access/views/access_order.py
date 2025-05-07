from rest_framework import viewsets, permissions, status
from rest_framework.decorators import action
from rest_framework.response import Response

from ..models import AccessOrder
from ..serializers import AccessOrderSerializer, ClientAccessSerializer


class AccessOrderViewSet(viewsets.ModelViewSet):
    serializer_class = AccessOrderSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_serializer_class(self):
        if self.action == 'my_clients':
            return ClientAccessSerializer
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
