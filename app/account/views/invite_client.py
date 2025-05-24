from drf_spectacular.utils import extend_schema
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from account.serializers.invite_client import InviteClientSerializer
from account.services.invite_client import invite_client
from chat_access.serializers import ChatListSerializer


class InviteClientView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        summary="Пригласить клиента",
        description="Специалист указывает номер клиента и бесплатный тариф. "
                    "Если клиент уже зарегистрирован — создаётся чат и доступ. "
                    "Если нет — создаётся пользователь и отправляется SMS.",
        request=InviteClientSerializer,
        responses={201: ChatListSerializer}
    )
    def post(self, request):
        serializer = InviteClientSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        phone_number = serializer.validated_data['phone_number']
        tariff_id = serializer.validated_data['tariff_id']
        specialist = request.user

        chat = invite_client(phone_number=phone_number, tariff_id=tariff_id, specialist=specialist)

        return Response(ChatListSerializer(chat, context={'request': request}).data, status=201)
