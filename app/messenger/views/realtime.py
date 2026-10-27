from django.conf import settings
from drf_spectacular.utils import extend_schema, inline_serializer
from rest_framework import serializers
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from common.errors import AppError, ErrorCode
from messenger.clients import centrifugo
from messenger.services import access, attachments, presence


def _realtime_unavailable():
    return AppError(
        "Realtime временно недоступен",
        code=ErrorCode.REALTIME_UNAVAILABLE,
        status_code=503,
    )


ConnectionTokenResponseSerializer = inline_serializer(
    name="ConnectionToken",
    fields={
        "token": serializers.CharField(),
        "ws_url": serializers.CharField(),
        "expires_at": serializers.DateTimeField(),
        "limits": inline_serializer(
            name="UploadLimits",
            fields={
                "image_max_bytes": serializers.IntegerField(),
                "video_max_bytes": serializers.IntegerField(),
                "file_max_bytes": serializers.IntegerField(),
                "voice_max_bytes": serializers.IntegerField(),
                "max_attachments_per_message": serializers.IntegerField(),
            },
        ),
    },
)


@extend_schema(tags=["Messenger"])
class ConnectionTokenView(APIView):
    """Токен подключения к Centrifugo (личный канал подписывается сервером) и лимиты загрузки."""

    permission_classes = [IsAuthenticated]

    @extend_schema(responses=ConnectionTokenResponseSerializer)
    def get(self, request):
        try:
            token, expires_at = centrifugo.connection_token(request.user.pk)
        except centrifugo.CentrifugoError:
            raise _realtime_unavailable()
        presence.touch(request.user.pk)
        return Response(
            {
                "token": token,
                "ws_url": settings.CENTRIFUGO_WS_URL,
                "expires_at": expires_at,
                "limits": attachments.upload_limits(),
            }
        )


@extend_schema(tags=["Messenger"])
class SubscriptionTokenView(APIView):
    """Токен подписки на канал чата `chat:<channel_id>`; только для участников."""

    permission_classes = [IsAuthenticated]

    def get(self, request, channel_id):
        chat = access.ensure_member(request.user, channel_id)
        channel = f"chat:{chat.channel_id}"
        try:
            token = centrifugo.subscription_token(request.user.pk, channel)
        except centrifugo.CentrifugoError:
            raise _realtime_unavailable()
        return Response({"token": token, "channel": channel})
