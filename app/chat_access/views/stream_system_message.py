import logging

from rest_framework import viewsets, status
from rest_framework.response import Response

from account.services import send_system_message_once
from messenger.services import system_messages as messenger_system_messages
from ..models import Chat
from ..serializers import StreamSystemMessageSerializer
from common.errors import ErrorCode, error_response

logger = logging.getLogger(__name__)


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
            return error_response(
                ErrorCode.CHAT_NOT_FOUND,
                "Chat not found",
                status.HTTP_404_NOT_FOUND,
                success=False,
                error="Chat not found",
            )

        client_name = chat.client.get_full_name()
        specialist_name = chat.specialist.get_full_name()

        # === Отправляем системное сообщение ===
        result = send_system_message_once(channel_id, custom_type, text)

        # Переходный период: то же сообщение пишем и в свой мессенджер (двойная запись).
        # Ошибка нашей БД не должна ломать старое приложение, работающее через Stream.
        try:
            messenger_system_messages.send_system_message_once(chat, custom_type, text)
        except Exception:
            logger.exception("Failed to write system message %s to messenger for %s", custom_type, channel_id)

        return Response({
            "success": bool(result),
            "client_name": client_name,
            "specialist_name": specialist_name
        })
