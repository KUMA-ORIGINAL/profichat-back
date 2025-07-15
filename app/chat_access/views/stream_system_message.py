from rest_framework import viewsets, status
from rest_framework.response import Response

from account.services import send_system_message_once
from chat_access.models import Chat
from ..serializers import StreamSystemMessageSerializer


class StreamSystemMessageViewSet(viewsets.ViewSet):
    """
        POST /api/stream/send_system_message/
        {
            "channel_id": 123,
            "custom_type": "tariffExpired",
            "text": "Необязательный текст"
        }
    """
    serializer_class = StreamSystemMessageSerializer

    def create(self, request):
        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        channel_id = data['channel_id']
        custom_type = data['custom_type']
        text = data.get('text')

        if not channel_id or not custom_type:
            return Response(
                {"success": False, "error": "channel_id and custom_type are required"},
                status=status.HTTP_400_BAD_REQUEST
            )

        result = send_system_message_once(channel_id, custom_type, text)
        if result:
            return Response({"success": True})
        else:
            return Response(
                {"success": False, "error": "Message was already sent or invalid type"},
                status=status.HTTP_200_OK
            )
