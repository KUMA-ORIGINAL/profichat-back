from django.utils import timezone
from drf_spectacular.utils import (
    OpenApiExample,
    OpenApiResponse,
    extend_schema,
    inline_serializer,
)
from push_notifications.models import GCMDevice
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework import serializers
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
            200: OpenApiResponse(
                response=inline_serializer(
                    name="RegisterFCMTokenResponse",
                    fields={
                        "status": serializers.CharField(),
                        "created": serializers.BooleanField(),
                    },
                ),
                description="Token registered successfully",
            ),
            400: OpenApiResponse(description="Missing or invalid data"),
        },
        summary="Register FCM token",
        description="Привязывает FCM токен к авторизованному пользователю",
        examples=[
            OpenApiExample(
                "Request example",
                value={"registrationId": "eYJ1....FCM_TOKEN....X6n"},
                request_only=True,
            ),
            OpenApiExample(
                "Response example",
                value={"status": "success", "created": True},
                response_only=True,
            ),
        ],
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
        summary="List notifications",
        description="Возвращает историю уведомлений текущего пользователя с пагинацией.",
        responses={
            200: OpenApiResponse(
                response=NotificationSerializer(many=True),
                description="Notifications list",
            )
        },
        examples=[
            OpenApiExample(
                "Notification item example",
                value={
                    "id": 101,
                    "notificationType": "chat_invite",
                    "title": "Новый чат",
                    "message": "Вас пригласили в чат со специалистом",
                    "payload": {
                        "chatId": "42",
                        "type": "chat_invite",
                        "channelId": "chat_15_7",
                        "senderName": "Иван Иванов",
                        "senderId": "7",
                    },
                    "isRead": False,
                    "readAt": None,
                    "createdAt": "2026-03-23T21:00:00+06:00",
                },
                response_only=True,
            )
        ],
    )
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    @extend_schema(
        summary="Unread notifications count",
        description="Возвращает количество непрочитанных уведомлений текущего пользователя.",
        responses={
            200: OpenApiResponse(
                response=inline_serializer(
                    name="UnreadNotificationsCountResponse",
                    fields={"unread_count": serializers.IntegerField(min_value=0)},
                ),
                description="Unread count returned",
            )
        },
        examples=[
            OpenApiExample(
                "Unread count example",
                value={"unreadCount": 3},
                response_only=True,
            )
        ],
    )
    @action(detail=False, methods=["get"], url_path="unread-count")
    def unread_count(self, request):
        unread = self.get_queryset().filter(is_read=False).count()
        return Response({"unread_count": unread})

    @extend_schema(
        summary="Mark one notification as read",
        description="Помечает одно уведомление как прочитанное.",
        responses={
            200: OpenApiResponse(
                response=inline_serializer(
                    name="MarkReadResponse",
                    fields={"status": serializers.CharField()},
                ),
                description="Notification marked as read",
            )
        },
        examples=[
            OpenApiExample(
                "Mark read response",
                value={"status": "success"},
                response_only=True,
            )
        ],
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
        description="Помечает несколько уведомлений как прочитанные (только текущего пользователя).",
        responses={
            200: OpenApiResponse(
                response=inline_serializer(
                    name="MarkReadBulkResponse",
                    fields={
                        "status": serializers.CharField(),
                        "updated_count": serializers.IntegerField(min_value=0),
                    },
                ),
                description="Notifications marked as read",
            )
        },
        examples=[
            OpenApiExample(
                "Mark read bulk request",
                value={"notificationIds": [101, 102, 103]},
                request_only=True,
            ),
            OpenApiExample(
                "Mark read bulk response",
                value={"status": "success", "updatedCount": 3},
                response_only=True,
            ),
        ],
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


@extend_schema(tags=["Notifications"])
class PushStatusView(APIView):
    """Состояние доставки push для текущего пользователя.

    Нужен клиенту, чтобы понять, что пуши не дойдут (токен протух, устройство
    не зарегистрировано), и показать подсказку вместо молчаливой тишины.
    """

    permission_classes = [IsAuthenticated]

    REASON_OK = "ok"
    REASON_NO_DEVICES = "no_devices"
    REASON_TOKEN_INVALID = "token_invalid"
    REASON_PROVIDER_ERROR = "provider_error"
    REASON_UNKNOWN = "unknown"

    REASON_MESSAGES = {
        REASON_OK: "Push-уведомления работают",
        REASON_NO_DEVICES: "Устройство не зарегистрировано для push-уведомлений",
        REASON_TOKEN_INVALID: "Токен устройства недействителен, зарегистрируйте его заново",
        REASON_PROVIDER_ERROR: "Сервис push-уведомлений вернул ошибку при последней отправке",
        REASON_UNKNOWN: "Пока не было ни одной отправки push на это устройство",
    }

    @extend_schema(
        summary="Push delivery status",
        description=(
            "Возвращает, дойдут ли push-уведомления до текущего пользователя: "
            "есть ли активные устройства, когда была последняя успешная отправка "
            "и причина последней ошибки."
        ),
        responses={
            200: OpenApiResponse(
                response=inline_serializer(
                    name="PushStatusResponse",
                    fields={
                        "push_enabled": serializers.BooleanField(),
                        "reason": serializers.CharField(),
                        "message": serializers.CharField(),
                        "action": serializers.CharField(allow_blank=True),
                        "active_devices": serializers.IntegerField(min_value=0),
                        "total_devices": serializers.IntegerField(min_value=0),
                        "last_success_at": serializers.DateTimeField(allow_null=True),
                        "last_failure_at": serializers.DateTimeField(allow_null=True),
                        "last_error_code": serializers.CharField(allow_blank=True),
                    },
                ),
                description="Push status",
            )
        },
        examples=[
            OpenApiExample(
                "Токен протух",
                value={
                    "pushEnabled": False,
                    "reason": "token_invalid",
                    "message": "Токен устройства недействителен, зарегистрируйте его заново",
                    "action": "reregister_token",
                    "activeDevices": 0,
                    "totalDevices": 1,
                    "lastSuccessAt": "2026-08-01T10:15:00+06:00",
                    "lastFailureAt": "2026-08-19T09:00:00+06:00",
                    "lastErrorCode": "UNREGISTERED",
                },
                response_only=True,
            ),
        ],
    )
    def get(self, request):
        devices = GCMDevice.objects.filter(user=request.user).select_related("delivery_status")
        active_devices = [d for d in devices if d.active]
        statuses = [d.delivery_status for d in devices if getattr(d, "delivery_status", None)]

        success_times = [s.last_success_at for s in statuses if s.last_success_at]
        failure_times = [s.last_failure_at for s in statuses if s.last_failure_at]
        last_success_at = max(success_times) if success_times else None
        last_failure_at = max(failure_times) if failure_times else None

        last_error_code = ""
        if last_failure_at:
            last_error_code = next(
                (s.last_error_code for s in statuses if s.last_failure_at == last_failure_at),
                "",
            )

        if not active_devices:
            reason = self.REASON_TOKEN_INVALID if devices else self.REASON_NO_DEVICES
            action_hint = "reregister_token"
        elif last_success_at and (not last_failure_at or last_success_at >= last_failure_at):
            reason, action_hint = self.REASON_OK, ""
        elif last_failure_at:
            reason, action_hint = self.REASON_PROVIDER_ERROR, "retry_later"
        else:
            reason, action_hint = self.REASON_UNKNOWN, ""

        return Response(
            {
                "push_enabled": reason == self.REASON_OK,
                "reason": reason,
                "message": self.REASON_MESSAGES[reason],
                "action": action_hint,
                "active_devices": len(active_devices),
                "total_devices": len(devices),
                "last_success_at": last_success_at,
                "last_failure_at": last_failure_at,
                "last_error_code": last_error_code,
            },
            status=status.HTTP_200_OK,
        )
