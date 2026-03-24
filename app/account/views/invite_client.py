from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from account.models import InviteDelivery
from account.serializers.invite_client import (
    InviteClientSerializer,
    InviteDeliverySerializer,
    InviteDeliveryListQuerySerializer,
)
from account.services.invite_client import invite_client
from chat_access.serializers import ChatListSerializer
from chat_access.services import build_chat_list_item, get_should_reply_map


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
        note = serializer.validated_data.get('note', '')
        specialist = request.user

        chat, _delivery = invite_client(
            phone_number=phone_number, 
            tariff_id=tariff_id, 
            specialist=specialist,
            note=note
        )

        chat_payload = build_chat_list_item(
            chat,
            specialist,
            should_reply_map=get_should_reply_map([chat], specialist),
        )
        return Response(ChatListSerializer(chat_payload, context={'request': request}).data, status=201)


class InviteDeliveryStatusView(APIView):
    permission_classes = [IsAuthenticated]
    serializer_class = InviteDeliverySerializer

    @extend_schema(
        summary="История доставки приглашений",
        description=(
            "Возвращает историю отправок приглашений (SMS/Push) по текущему специалисту. "
            "Можно отфильтровать по chat_id."
        ),
        parameters=[
            OpenApiParameter(name="chat_id", type=int, required=False, location=OpenApiParameter.QUERY),
            OpenApiParameter(name="limit", type=int, required=False, location=OpenApiParameter.QUERY),
        ],
        # responses={200: InviteDeliverySerializer(many=True)},
    )
    def get(self, request):
        query_serializer = InviteDeliveryListQuerySerializer(data=request.query_params)
        query_serializer.is_valid(raise_exception=True)

        chat_id = query_serializer.validated_data.get("chat_id")
        limit = query_serializer.validated_data.get("limit", 20)

        queryset = InviteDelivery.objects.filter(specialist=request.user)
        if chat_id is not None:
            queryset = queryset.filter(chat_id=chat_id)

        deliveries = queryset.select_related("chat", "client").order_by("-created_at")[:limit]
        data = InviteDeliverySerializer(deliveries, many=True).data
        return Response(data)
