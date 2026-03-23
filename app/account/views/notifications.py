from django.utils import timezone
from drf_spectacular.utils import OpenApiResponse, extend_schema
from push_notifications.models import GCMDevice
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from ..models import Notification
from ..serializers import (
    NotificationReadSerializer,
    NotificationSerializer,
    RegisterFCMTokenSerializer,
)


class RegisterFCMTokenView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        request=RegisterFCMTokenSerializer,
        responses={
            200: OpenApiResponse(description="Token registered successfully"),
            400: OpenApiResponse(description="Missing or invalid data"),
        },
        summary="Register FCM token",
        description="Привязывает FCM токен к авторизованному пользователю"
    )
    def post(self, request):
        serializer = RegisterFCMTokenSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        reg_id = serializer.validated_data["registration_id"]

        device, created = GCMDevice.objects.update_or_create(
            registration_id=reg_id,
            defaults={"user": request.user, "active": True}
        )
        return Response({"status": "success", "created": created})


class NotificationPagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 100


@extend_schema(tags=["Notifications"])
class NotificationViewSet(viewsets.GenericViewSet, mixins.ListModelMixin):
    serializer_class = NotificationSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = NotificationPagination

    def get_queryset(self):
        return Notification.objects.filter(recipient=self.request.user).order_by("-created_at")

    @extend_schema(
        summary="Unread notifications count",
        responses={200: OpenApiResponse(description="Unread count returned")},
    )
    @action(detail=False, methods=["get"], url_path="unread-count")
    def unread_count(self, request):
        unread = self.get_queryset().filter(is_read=False).count()
        return Response({"unread_count": unread})

    @extend_schema(
        summary="Mark one notification as read",
        responses={200: OpenApiResponse(description="Notification marked as read")},
    )
    @action(detail=True, methods=["post"], url_path="mark-read")
    def mark_read(self, request, pk=None):
        notification = self.get_object()
        if not notification.is_read:
            notification.is_read = True
            notification.read_at = timezone.now()
            notification.save(update_fields=["is_read", "read_at", "updated_at"])
        return Response({"status": "success"})

    @extend_schema(
        request=NotificationReadSerializer,
        summary="Mark multiple notifications as read",
        responses={200: OpenApiResponse(description="Notifications marked as read")},
    )
    @action(detail=False, methods=["post"], url_path="mark-read")
    def mark_read_bulk(self, request):
        serializer = NotificationReadSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        notification_ids = serializer.validated_data["notification_ids"]
        updated = self.get_queryset().filter(
            id__in=notification_ids,
            is_read=False,
        ).update(is_read=True, read_at=timezone.now(), updated_at=timezone.now())

        return Response({"status": "success", "updated_count": updated}, status=status.HTTP_200_OK)
