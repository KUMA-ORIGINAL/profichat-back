import json
import logging

from drf_spectacular.utils import extend_schema
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from account.services.stream import is_old_app_message_event, send_outdated_app_notice
from common.errors import AppError, ErrorCode
from common.stream_client import chat_client

logger = logging.getLogger(__name__)

__all__ = ["StreamWebhookView"]


@extend_schema(exclude=True)
class StreamWebhookView(APIView):
    """
    Вебхук GetStream (webhook_url в настройках приложения Stream). После переключения на свой мессенджер
    отвечает в канал «обновите приложение» со ссылками на сторы на сообщения из старых версий. Аутентификация — только
    подпись X-Signature (HMAC-SHA256 сырого тела секретом Stream).
    """

    authentication_classes = []
    permission_classes = [AllowAny]

    def post(self, request):
        # сырое тело читается до request.data: подпись считается по байтам как есть
        body = request.body
        if not chat_client.verify_webhook(body, request.headers.get("X-Signature", "")):
            logger.warning("[Stream] webhook rejected: bad signature")
            raise AppError("Неверная подпись вебхука", code=ErrorCode.NOT_AUTHENTICATED, status_code=401)

        event = json.loads(body)
        if is_old_app_message_event(event):
            send_outdated_app_notice(event.get("channel_type") or "messaging", event["channel_id"])
        return Response({"status": "ok"})
