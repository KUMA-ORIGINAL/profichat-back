from drf_spectacular.utils import extend_schema, inline_serializer
from rest_framework import serializers
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from account.services.stream import ALLOWED_TYPES
from messenger.services import access, system_messages


class SystemMessageRequestSerializer(serializers.Serializer):
    custom_type = serializers.ChoiceField(choices=ALLOWED_TYPES)
    text = serializers.CharField(required=False, allow_blank=True, allow_null=True, max_length=10000)


SystemMessageResponseSerializer = inline_serializer(
    name="SystemMessageResult",
    fields={
        "success": serializers.BooleanField(),
        "client_name": serializers.CharField(),
        "specialist_name": serializers.CharField(),
    },
)


@extend_schema(tags=["Messenger"])
class ChatSystemMessageView(APIView):
    """Системное сообщение в чат (тариф выдан/истёк/активирован, чат заблокирован) с дедупом 600 с."""

    permission_classes = [IsAuthenticated]

    @extend_schema(
        summary="Send system message",
        request=SystemMessageRequestSerializer,
        responses=SystemMessageResponseSerializer,
    )
    def post(self, request, channel_id):
        chat = access.ensure_member(request.user, channel_id)
        serializer = SystemMessageRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        message = system_messages.send_system_message_once(
            chat,
            serializer.validated_data["custom_type"],
            serializer.validated_data.get("text"),
        )
        return Response(
            {
                "success": message is not None,
                "client_name": chat.client.get_full_name(),
                "specialist_name": chat.specialist.get_full_name(),
            }
        )
