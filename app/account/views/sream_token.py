from drf_spectacular.utils import extend_schema
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from ..stream_client import chat_client


@extend_schema(
    tags=['Get Stream Token'],
)
class GetStreamTokenView(APIView):
    """
    API для генерации токена GetStream
    """
    permission_classes = (IsAuthenticated,)

    def get(self, request):
        user = request.user
        token = chat_client.create_token(str(user.id))  # Генерация токена
        return Response({"stream_token": token})
