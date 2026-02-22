import logging

from django.contrib.auth import get_user_model
from drf_spectacular.utils import extend_schema, OpenApiParameter
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from account.models.user import ROLE_SPECIALIST
from account.services.invite_client import invite_client
from chat_access.models import Tariff
from integrations.authentication import MedCRMApiKeyAuthentication
from integrations.permissions import IsMedCRMAuthenticated
from integrations.serializers import (
    MedCRMTariffSerializer,
    MedCRMInviteClientSerializer,
    MedCRMInviteResponseSerializer,
)

logger = logging.getLogger(__name__)
User = get_user_model()


class MedCRMTariffsView(APIView):
    """Получение тарифов специалиста по номеру телефона."""

    authentication_classes = [MedCRMApiKeyAuthentication]
    permission_classes = [IsMedCRMAuthenticated]

    @extend_schema(
        summary="[MedCRM] Получить тарифы специалиста",
        description="Возвращает список активных тарифов специалиста по его номеру телефона.",
        parameters=[
            OpenApiParameter(
                name="phone_number",
                type=str,
                location=OpenApiParameter.QUERY,
                required=True,
                description="Номер телефона специалиста (например +996700123456)",
            ),
        ],
        responses={200: MedCRMTariffSerializer(many=True)},
        tags=["MedCRM Integration"],
    )
    def get(self, request):
        phone_number = request.query_params.get("phone_number")
        if not phone_number:
            return Response(
                {"detail": "Параметр phone_number обязателен."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        specialist = User.objects.filter(
            phone_number=phone_number,
            role=ROLE_SPECIALIST,
            is_active=True,
        ).first()

        if not specialist:
            return Response(
                {"detail": "Специалист с таким номером не найден."},
                status=status.HTTP_404_NOT_FOUND,
            )

        tariffs = Tariff.objects.filter(
            specialist=specialist,
            is_archive=False,
            is_active=True,
        )

        serializer = MedCRMTariffSerializer(tariffs, many=True)
        return Response(serializer.data)


class MedCRMInviteClientView(APIView):
    """Приглашение клиента от имени специалиста по номеру телефона."""

    authentication_classes = [MedCRMApiKeyAuthentication]
    permission_classes = [IsMedCRMAuthenticated]

    @extend_schema(
        summary="[MedCRM] Пригласить клиента",
        description=(
            "Специалист (по номеру телефона) приглашает клиента (по номеру телефона) "
            "с указанием тарифа. Создаётся чат и бесплатный доступ. "
            "Новому клиенту отправляется SMS, существующему — push."
        ),
        request=MedCRMInviteClientSerializer,
        responses={201: MedCRMInviteResponseSerializer},
        tags=["MedCRM Integration"],
    )
    def post(self, request):
        serializer = MedCRMInviteClientSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        specialist_phone = serializer.validated_data["specialist_phone_number"]
        client_phone = serializer.validated_data["client_phone_number"]
        tariff_id = serializer.validated_data["tariff_id"]
        note = serializer.validated_data.get("note", "")

        specialist = User.objects.filter(
            phone_number=specialist_phone,
            role=ROLE_SPECIALIST,
            is_active=True,
        ).first()

        if not specialist:
            return Response(
                {"detail": "Специалист с таким номером не найден."},
                status=status.HTTP_404_NOT_FOUND,
            )

        tariff = Tariff.objects.filter(
            id=tariff_id,
            specialist=specialist,
            is_archive=False,
        ).first()

        if not tariff:
            return Response(
                {"detail": "Тариф не найден или не принадлежит данному специалисту."},
                status=status.HTTP_404_NOT_FOUND,
            )

        existing_client = User.objects.filter(phone_number=client_phone).exists()

        chat = invite_client(
            phone_number=client_phone,
            tariff_id=tariff_id,
            specialist=specialist,
            note=note,
        )

        client = chat.client

        response_data = {
            "chat_id": chat.id,
            "channel_id": chat.channel_id,
            "client_id": client.id,
            "is_new_client": not existing_client,
        }

        logger.info(
            "MedCRM invite: specialist=%s -> client=%s, tariff=%s, chat=%s",
            specialist_phone, client_phone, tariff_id, chat.channel_id,
        )

        return Response(response_data, status=status.HTTP_201_CREATED)
