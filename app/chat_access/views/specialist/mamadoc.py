from django.contrib.auth import get_user_model
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import extend_schema, OpenApiParameter
from rest_framework import viewsets, permissions, status
from rest_framework.decorators import action
from rest_framework.response import Response

from account.models import ROLE_SPECIALIST
from chat_access.models import Chat
from chat_access.serializers.specialist.mamadoc import (
    MamaDocClientIdQuerySerializer,
    MamaDocConclusionQuerySerializer,
    MamaDocConclusionDetailSerializer,
    MamaDocVisitSerializer,
)
from integrations.mamadoc import client as mamadoc_client
from integrations.mamadoc.client import MamaDocAPIError

User = get_user_model()


class SpecialistMamaDocViewSet(viewsets.GenericViewSet):
    """
    API для просмотра истории визитов и заключений NewCRM (Аксима CRM)
    по клиенту, с которым у специалиста есть чат в Профиграме.
    """
    permission_classes = [permissions.IsAuthenticated]

    def _forbid_if_not_specialist(self, request):
        if request.user.role != ROLE_SPECIALIST:
            return Response(
                {"detail": "Only specialists can view NewCRM history."},
                status=status.HTTP_403_FORBIDDEN,
            )
        return None

    def _get_authorized_client(self, request, client_id):
        if not Chat.objects.filter(specialist=request.user, client_id=client_id).exists():
            return None
        return get_object_or_404(User, pk=client_id)

    def _resolve_patient_id(self, client_user):
        if not client_user.phone_number:
            return None
        return mamadoc_client.find_patient_id_by_phone(str(client_user.phone_number))

    def _error_response(self, e: MamaDocAPIError):
        detail = e.detail if isinstance(e.detail, (dict, list)) else {"detail": e.detail}
        return Response(detail, status=e.status_code)

    @extend_schema(
        parameters=[OpenApiParameter(name="client_id", type=int, location=OpenApiParameter.QUERY, required=True)],
        summary="История визитов клиента в NewCRM (Аксима CRM)",
    )
    @action(detail=False, methods=["get"], url_path="visits")
    def visits(self, request):
        forbidden = self._forbid_if_not_specialist(request)
        if forbidden is not None:
            return forbidden

        query_serializer = MamaDocClientIdQuerySerializer(data=request.query_params)
        query_serializer.is_valid(raise_exception=True)
        client_id = query_serializer.validated_data["client_id"]

        client_user = self._get_authorized_client(request, client_id)
        if client_user is None:
            return Response(
                {"detail": "Client not found or no chat with this client."},
                status=status.HTTP_404_NOT_FOUND,
            )

        try:
            patient_id = self._resolve_patient_id(client_user)
            if patient_id is None:
                return Response({"linked": False, "visits": []})

            appointments = mamadoc_client.list_appointments(patient_id)
        except MamaDocAPIError as e:
            return self._error_response(e)

        visits = MamaDocVisitSerializer(appointments, many=True).data
        return Response({"linked": True, "visits": visits})

    @extend_schema(
        parameters=[
            OpenApiParameter(name="client_id", type=int, location=OpenApiParameter.QUERY, required=True),
            OpenApiParameter(name="conclusion_id", type=int, location=OpenApiParameter.QUERY, required=True),
        ],
        summary="Детали медицинского заключения NewCRM (Аксима CRM)",
    )
    @action(detail=False, methods=["get"], url_path="conclusion")
    def conclusion(self, request):
        forbidden = self._forbid_if_not_specialist(request)
        if forbidden is not None:
            return forbidden

        query_serializer = MamaDocConclusionQuerySerializer(data=request.query_params)
        query_serializer.is_valid(raise_exception=True)
        client_id = query_serializer.validated_data["client_id"]
        conclusion_id = query_serializer.validated_data["conclusion_id"]

        client_user = self._get_authorized_client(request, client_id)
        if client_user is None:
            return Response(
                {"detail": "Client not found or no chat with this client."},
                status=status.HTTP_404_NOT_FOUND,
            )

        try:
            patient_id = self._resolve_patient_id(client_user)
            if patient_id is None:
                return Response({"detail": "Client is not linked to NewCRM."}, status=status.HTTP_404_NOT_FOUND)

            appointments = mamadoc_client.list_appointments(patient_id)
            known_conclusion_ids = {
                line.get("conclusionId")
                for appointment in appointments
                for line in appointment.get("serviceLines", [])
            }
            if conclusion_id not in known_conclusion_ids:
                return Response(
                    {"detail": "Conclusion does not belong to this client."},
                    status=status.HTTP_404_NOT_FOUND,
                )

            conclusion_data = mamadoc_client.get_conclusion(conclusion_id)
        except MamaDocAPIError as e:
            return self._error_response(e)

        if conclusion_data is None:
            return Response({"detail": "Conclusion not found."}, status=status.HTTP_404_NOT_FOUND)

        return Response(MamaDocConclusionDetailSerializer(conclusion_data).data)
