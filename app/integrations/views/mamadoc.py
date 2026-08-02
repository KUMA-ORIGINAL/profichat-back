import logging
from datetime import timezone as dt_timezone

from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import serializers, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from account.models.user import ROLE_SPECIALIST
from integrations.mamadoc import client as mamadoc_client
from integrations.mamadoc.client import MamaDocAPIError

logger = logging.getLogger(__name__)


class IsSpecialist(IsAuthenticated):
    """Доступ только для аутентифицированных пользователей с ролью специалиста."""

    def has_permission(self, request, view):
        return super().has_permission(request, view) and request.user.role == ROLE_SPECIALIST


def _error_response(e: MamaDocAPIError):
    logger.warning("NewCRM request failed: %s", e.detail)
    detail = e.detail if isinstance(e.detail, (dict, list)) else {"detail": e.detail}
    return Response(detail, status=e.status_code)


class MamadocAppointmentsView(APIView):
    permission_classes = [IsSpecialist]

    @extend_schema(
        summary="[NewCRM] Получить историю приемов",
        description="Возвращает историю приемов пациента из NewCRM по номеру телефона.",
        parameters=[
            OpenApiParameter(
                name="phone_number",
                type=str,
                location=OpenApiParameter.QUERY,
                required=True,
                description="Номер телефона пациента (например +996700123456)",
            ),
        ],
        responses={
            200: dict,
            400: {"description": "Не передан номер телефона (Bad Request)", "example": {"detail": "Параметр phone_number обязателен."}},
            502: {"description": "Ошибка ответа NewCRM", "example": {"detail": "Ошибка при получении данных из NewCRM."}},
        },
        tags=["NewCRM Integration"],
    )
    def get(self, request):
        phone_number = request.query_params.get("phone_number")
        if not phone_number:
            return Response(
                {"detail": "Параметр phone_number обязателен."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            patient_id = mamadoc_client.find_patient_id_by_phone(phone_number)
            if not patient_id:
                return Response([])
            appointments = mamadoc_client.list_appointments(patient_id)
        except MamaDocAPIError as e:
            return _error_response(e)

        appointments = [mamadoc_client.reformat_appointment_dates(a) for a in appointments]
        return Response(appointments)


class MamadocConclusionView(APIView):
    permission_classes = [IsSpecialist]

    @extend_schema(
        summary="[NewCRM] Получить детали заключения",
        description="Возвращает детальную медицинскую информацию по ID заключения.",
        responses={
            200: dict,
            404: {"description": "Заключение не найдено", "example": {"detail": "Заключение не найдено."}},
            502: {"description": "Ошибка ответа NewCRM", "example": {"detail": "Ошибка при получении данных из NewCRM."}},
        },
        tags=["NewCRM Integration"],
    )
    def get(self, request, conclusion_id):
        try:
            conclusion = mamadoc_client.get_conclusion(conclusion_id)
        except MamaDocAPIError as e:
            return _error_response(e)

        if conclusion is None:
            return Response({"detail": "Заключение не найдено."}, status=status.HTTP_404_NOT_FOUND)
        return Response(mamadoc_client.reformat_conclusion_dates(conclusion))


class MamadocBookingCreateSerializer(serializers.Serializer):
    branch_id = serializers.IntegerField()
    patient_id = serializers.IntegerField()
    employee_id = serializers.IntegerField()
    service_id = serializers.IntegerField()
    starts_at = serializers.DateTimeField(
        input_formats=["iso-8601", "%d.%m.%Y %H:%M", "%d.%m.%Y %H:%M:%S"],
        help_text=(
            "Время записи. Форматы: '05.08.2026 10:00' (время по Бишкеку) "
            "или ISO 2026-08-05T10:00:00+06:00"
        ),
    )
    status = serializers.CharField(default="scheduled", required=False)


class MamadocBookingView(APIView):
    """
    Брони специалиста в NewCRM.

    employee_id передаётся явно вызывающей стороной (query для GET, поле в
    теле для POST). Эндпоинт доступен только аутентифицированным специалистам
    Профиграма, но не ограничивает их только собственным employee_id —
    это осознанное решение продукта, а не привязка к телефону вызывающего.
    """

    permission_classes = [IsSpecialist]

    @extend_schema(
        summary="[NewCRM] Получить брони специалиста",
        description="Возвращает список броней специалиста по его employee_id в NewCRM. Поддерживает фильтрацию по датам и статусу.",
        parameters=[
            OpenApiParameter(
                name="employee_id",
                type=int,
                location=OpenApiParameter.QUERY,
                required=True,
                description="ID врача (сотрудника) в NewCRM",
            ),
            OpenApiParameter(
                name="start_date",
                type=str,
                location=OpenApiParameter.QUERY,
                required=False,
                description="Начальная дата (ISO 8601, например 2026-08-01)",
            ),
            OpenApiParameter(
                name="end_date",
                type=str,
                location=OpenApiParameter.QUERY,
                required=False,
                description="Конечная дата (ISO 8601, например 2026-08-31)",
            ),
            OpenApiParameter(
                name="status",
                type=str,
                location=OpenApiParameter.QUERY,
                required=False,
                description="Статус записи (например, scheduled, completed, canceled)",
            ),
        ],
        responses={
            200: dict,
            400: {"description": "Не передан employee_id"},
            502: {"description": "Ошибка ответа NewCRM"},
        },
        tags=["NewCRM Integration"],
    )
    def get(self, request):
        employee_id = request.query_params.get("employee_id")
        if not employee_id:
            return Response(
                {"detail": "Параметр employee_id обязателен."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            employee_id = int(employee_id)
        except ValueError:
            return Response({"detail": "employee_id должен быть числом."}, status=status.HTTP_400_BAD_REQUEST)

        try:
            appointments = mamadoc_client.list_employee_appointments(
                employee_id=employee_id,
                start_date=request.query_params.get("start_date"),
                end_date=request.query_params.get("end_date"),
                status=request.query_params.get("status"),
            )
        except MamaDocAPIError as e:
            return _error_response(e)

        appointments = [mamadoc_client.reformat_appointment_dates(a) for a in appointments]
        return Response(appointments)

    @extend_schema(
        summary="[NewCRM] Создать новую запись (бронь)",
        description="Создает запись к указанному специалисту (employee_id) в NewCRM.",
        request=MamadocBookingCreateSerializer,
        responses={
            201: dict,
            400: {"description": "Ошибка валидации NewCRM (например, неверный ID)"},
            502: {"description": "Ошибка ответа NewCRM"},
        },
        tags=["NewCRM Integration"],
    )
    def post(self, request):
        serializer = MamadocBookingCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        starts_at_utc = data["starts_at"].astimezone(dt_timezone.utc)
        starts_at_iso = starts_at_utc.strftime("%Y-%m-%dT%H:%M:%SZ")

        try:
            result = mamadoc_client.create_appointment(
                branch_id=data["branch_id"],
                patient_id=data["patient_id"],
                employee_id=data["employee_id"],
                service_id=data["service_id"],
                starts_at_iso=starts_at_iso,
                status=data.get("status", "scheduled"),
            )
        except MamaDocAPIError as e:
            return _error_response(e)

        return Response(mamadoc_client.reformat_appointment_dates(result), status=status.HTTP_201_CREATED)


class MamadocBookingCancelSerializer(serializers.Serializer):
    reason = serializers.CharField(required=False, allow_blank=True, default="")


class MamadocBookingCancelView(APIView):
    """Отмена записи (брони) в NewCRM: PATCH status=canceled."""

    permission_classes = [IsSpecialist]

    @extend_schema(
        summary="[NewCRM] Отменить запись (бронь)",
        description="Отменяет существующую запись по её ID в NewCRM (status -> canceled).",
        request=MamadocBookingCancelSerializer,
        responses={
            200: dict,
            404: {"description": "Запись не найдена"},
            400: {"description": "Ошибка валидации NewCRM (например, запись уже завершена)"},
            502: {"description": "Ошибка ответа NewCRM"},
        },
        tags=["NewCRM Integration"],
    )
    def patch(self, request, appointment_id):
        serializer = MamadocBookingCancelSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        reason = serializer.validated_data.get("reason", "")

        try:
            result = mamadoc_client.cancel_appointment(appointment_id, reason=reason)
        except MamaDocAPIError as e:
            return _error_response(e)

        return Response(mamadoc_client.reformat_appointment_dates(result), status=status.HTTP_200_OK)
