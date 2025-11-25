from rest_framework import viewsets, status
from rest_framework.response import Response

from account.services import send_system_message_once
from ..models import Chat
from ..serializers import StreamSystemMessageSerializer


class StreamSystemMessageViewSet(viewsets.ViewSet):
    serializer_class = StreamSystemMessageSerializer

    def create(self, request):
        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        channel_id = data['channel_id']
        custom_type = data['custom_type']
        text = data.get('text')

        # === Получаем чат ===
        try:
            chat = Chat.objects.select_related("client", "specialist").get(channel_id=channel_id)
        except Chat.DoesNotExist:
            return Response(
                {"success": False, "error": "Chat not found"},
                status=status.HTTP_404_NOT_FOUND
            )

        client_name = chat.client.get_full_name()
        specialist_name = chat.specialist.get_full_name()

        # === Отправляем системное сообщение ===
        result = send_system_message_once(channel_id, custom_type, text)

        return Response({
            "success": bool(result),
            "client_name": client_name,
            "specialist_name": specialist_name
        })
