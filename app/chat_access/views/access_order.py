import logging

from django.utils import timezone
from rest_framework import permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from ..models import AccessOrder
from ..serializers.access_order import (
    AccessOrderCreateSerializer,
    AccessOrderSerializer,
    CancelSubscriptionByChannelSerializer,
    ClientAccessSerializer,
    SpecialistSerializer,
)
from ..services import update_chat_data_from_order
from ..services.open_banking import generate_payment_link

logger = logging.getLogger(__name__)


class AccessOrderViewSet(viewsets.ModelViewSet):
    serializer_class = AccessOrderSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_serializer_class(self):
        if self.action == "my_clients":
            return ClientAccessSerializer
        if self.action == "create":
            return AccessOrderCreateSerializer
        return AccessOrderSerializer

    def get_queryset(self):
        return AccessOrder.objects.filter(client=self.request.user)

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        access_order = serializer.save()

        specialist_data = SpecialistSerializer(access_order.specialist).data

        if access_order.tariff_type == "free":
            access_order.payment_status = "success"
            access_order.activate()
            update_chat_data_from_order(access_order)
            return Response(
                {
                    "id": access_order.id,
                    "message": "Доступ активирован сразу, так как выбран бесплатный тариф.",
                },
                status=status.HTTP_201_CREATED,
            )

        payment_url = generate_payment_link(access_order)
        if not payment_url:
            return Response(
                {"detail": "Failed to generate payment link. Please try again later."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        data = {
            "id": access_order.id,
            "payment_url": payment_url,
            "specialist": specialist_data,
        }
        return Response(data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"], url_path="cancel-subscription")
    def cancel_subscription(self, request, pk=None):
        order = self.get_object()
        now = timezone.now()

        if order.payment_status == "cancelled":
            return Response({"detail": "Subscription already cancelled."}, status=status.HTTP_200_OK)

        if order.payment_status != "success" or not order.expires_at or order.expires_at <= now:
            return Response(
                {"detail": "Only active subscription can be cancelled."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        order.payment_status = "cancelled"
        order.expires_at = now
        order.save(update_fields=["payment_status", "expires_at"])

        if order.chat_id:
            try:
                update_chat_data_from_order(order)
            except Exception:
                logger.exception("Failed to sync chat extra data after cancellation for order %s", order.id)

        return Response(
            {"status": "success", "order_id": order.id, "payment_status": order.payment_status},
            status=status.HTTP_200_OK,
        )

    @action(detail=False, methods=["post"], url_path="cancel-subscription-by-channel")
    def cancel_subscription_by_channel(self, request):
        serializer = CancelSubscriptionByChannelSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        channel_id = serializer.validated_data["channel_id"]
        now = timezone.now()
        active_order = (
            AccessOrder.objects.filter(
                client=request.user,
                chat__channel_id=channel_id,
                payment_status="success",
                expires_at__gt=now,
            )
            .select_related("chat", "tariff")
            .order_by("-created_at")
            .first()
        )

        if active_order:
            active_order.payment_status = "cancelled"
            active_order.expires_at = now
            active_order.save(update_fields=["payment_status", "expires_at"])

            try:
                update_chat_data_from_order(active_order)
            except Exception:
                logger.exception(
                    "Failed to sync chat extra data after cancellation by channel %s (order %s)",
                    channel_id,
                    active_order.id,
                )

            return Response(
                {
                    "status": "success",
                    "channel_id": channel_id,
                    "order_id": active_order.id,
                    "payment_status": active_order.payment_status,
                },
                status=status.HTTP_200_OK,
            )

        latest_order = (
            AccessOrder.objects.filter(
                client=request.user,
                chat__channel_id=channel_id,
            )
            .order_by("-created_at")
            .first()
        )

        if latest_order and latest_order.payment_status == "cancelled":
            return Response(
                {
                    "status": "already_cancelled",
                    "channel_id": channel_id,
                    "order_id": latest_order.id,
                    "payment_status": latest_order.payment_status,
                },
                status=status.HTTP_200_OK,
            )

        if not latest_order:
            return Response(
                {"detail": "No subscription found for this channel."},
                status=status.HTTP_404_NOT_FOUND,
            )

        return Response(
            {
                "detail": "Only active subscription can be cancelled.",
                "channel_id": channel_id,
            },
            status=status.HTTP_400_BAD_REQUEST,
        )

    @action(detail=False, methods=["get"], url_path="last-for-specialist/(?P<specialist_id>[^/.]+)")
    def last_for_specialist(self, request, specialist_id=None):
        try:
            now = timezone.now()
            order = (
                AccessOrder.objects.filter(
                    client=request.user,
                    specialist_id=specialist_id,
                    payment_status="success",
                    expires_at__gt=now,
                )
                .order_by("-id")
                .first()
            )

            if order is None:
                return Response(
                    {"detail": "No access order found for this specialist."},
                    status=status.HTTP_404_NOT_FOUND,
                )

            serializer = self.get_serializer(order, context={"request": request})
            return Response(serializer.data)

        except Exception:
            logger.exception(
                "Failed to retrieve last access order for user_id=%s specialist_id=%s",
                request.user.id,
                specialist_id,
            )
            return Response(
                {"detail": "An error occurred while retrieving the access order."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    @action(detail=False, methods=["get"], url_path="my-clients")
    def my_clients(self, request):
        user = request.user

        if not hasattr(user, "role") or user.role != "specialist":
            return Response(
                {"detail": "Only specialists can view clients."},
                status=status.HTTP_403_FORBIDDEN,
            )

        orders = (
            AccessOrder.objects.filter(specialist=user)
            .select_related("client", "tariff")
            .order_by("-created_at")
        )

        latest_orders = {}
        for order in orders:
            if order.client_id not in latest_orders:
                latest_orders[order.client_id] = order

        serializer = ClientAccessSerializer(
            latest_orders.values(),
            many=True,
            context={"request": request},
        )
        return Response(serializer.data)
