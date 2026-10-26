import logging

from drf_spectacular.utils import extend_schema
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from common.errors import AppError, ErrorCode
from messenger.clients import livekit
from messenger.services import calls

logger = logging.getLogger(__name__)


@extend_schema(tags=["Messenger"], exclude=True)
class LiveKitWebhookView(APIView):
    """
    Вебхуки LiveKit. Аутентификация — только подпись: JWT в Authorization (ключ/секрет LiveKit)
    с sha256 сырого тела. JWT-аутентификация DRF отключена: LiveKit кладёт в Authorization свой токен.
    """

    authentication_classes = []
    permission_classes = [AllowAny]

    def post(self, request):
        # сырое тело читается до request.data: подпись считается по байтам как есть
        body = request.body.decode("utf-8", errors="replace")
        try:
            event = livekit.verify_webhook(body, request.headers.get("Authorization", ""))
        except livekit.WebhookVerificationError as exc:
            logger.warning("[LiveKit] webhook rejected: %s", exc)
            raise AppError("Неверная подпись вебхука", code=ErrorCode.NOT_AUTHENTICATED, status_code=401)

        calls.handle_livekit_event(event)
        return Response({"status": "ok"})
