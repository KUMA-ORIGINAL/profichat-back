import logging
from datetime import datetime as dt_datetime

from django.utils import timezone as dj_timezone
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


class MamadocProfessionalsView(APIView):
    """Каталог врачей клиники NewCRM — чтобы найти employeeId нужного врача."""

    permission_classes = [IsSpecialist]

    @extend_schema(
        summary="[NewCRM] Каталог врачей клиники",
        description=(
            "Возвращает список врачей клиники NewCRM (id, ФИО, фото, специальность). "
            "id из этого списка используется как employeeId в остальных эндпоинтах брони."
        ),
        parameters=[
            OpenApiParameter(
                name="organization_id",
                type=int,
                location=OpenApiParameter.QUERY,
                required=True,
                description="ID клиники (организации) в NewCRM",
            ),
        ],
        responses={
            200: dict,
            400: {"description": "Не передан organization_id"},
            502: {"description": "Ошибка ответа NewCRM"},
        },
        tags=["NewCRM Integration"],
    )
    def get(self, request):
        organization_id = request.query_params.get("organization_id")
        if not organization_id:
            return Response(
                {"detail": "Параметр organization_id обязателен."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            organization_id = int(organization_id)
        except ValueError:
            return Response({"detail": "organization_id должен быть числом."}, status=status.HTTP_400_BAD_REQUEST)

        try:
            professionals = mamadoc_client.list_professionals(organization_id)
        except MamaDocAPIError as e:
            return _error_response(e)

        return Response(professionals)


class MamadocServicesView(APIView):
    """Каталог услуг клиники NewCRM — чтобы показать стоимость перед созданием брони."""

    permission_classes = [IsSpecialist]

    @extend_schema(
        summary="[NewCRM] Каталог услуг клиники",
        description=(
            "Возвращает список услуг клиники NewCRM (id, название, цена, длительность). "
            "id из этого списка используется как serviceId при создании брони."
        ),
        parameters=[
            OpenApiParameter(
                name="organization_id",
                type=int,
                location=OpenApiParameter.QUERY,
                required=True,
                description="ID клиники (организации) в NewCRM",
            ),
        ],
        responses={
            200: dict,
            400: {"description": "Не передан organization_id"},
            502: {"description": "Ошибка ответа NewCRM"},
        },
        tags=["NewCRM Integration"],
    )
    def get(self, request):
        organization_id = request.query_params.get("organization_id")
        if not organization_id:
            return Response(
                {"detail": "Параметр organization_id обязателен."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            organization_id = int(organization_id)
        except ValueError:
            return Response({"detail": "organization_id должен быть числом."}, status=status.HTTP_400_BAD_REQUEST)

        try:
            services = mamadoc_client.list_services(organization_id)
        except MamaDocAPIError as e:
            return _error_response(e)

        return Response(services)


class MamadocOrganizationView(APIView):
    """Клиника, привязанная к партнёрскому ключу Профиграма."""

    permission_classes = [IsSpecialist]

    @extend_schema(
        summary="[NewCRM] Клиника, привязанная к ключу",
        description="Возвращает данные организации (клиники), к которой привязан партнёрский ключ.",
        responses={
            200: dict,
            404: {"description": "Организация не найдена"},
            502: {"description": "Ошибка ответа NewCRM"},
        },
        tags=["NewCRM Integration"],
    )
    def get(self, request):
        try:
            organization = mamadoc_client.get_organization()
        except MamaDocAPIError as e:
            return _error_response(e)

        if organization is None:
            return Response({"detail": "Организация не найдена."}, status=status.HTTP_404_NOT_FOUND)
        return Response(organization)


class MamadocBranchesView(APIView):
    """Филиалы клиники, привязанной к партнёрскому ключу — источник branchId."""

    permission_classes = [IsSpecialist]

    @extend_schema(
        summary="[NewCRM] Филиалы клиники",
        description=(
            "Возвращает филиалы клиники, привязанной к партнёрскому ключу. "
            "id из этого списка используется как branchId при создании брони."
        ),
        responses={
            200: dict,
            502: {"description": "Ошибка ответа NewCRM"},
        },
        tags=["NewCRM Integration"],
    )
    def get(self, request):
        try:
            branches = mamadoc_client.list_branches()
        except MamaDocAPIError as e:
            return _error_response(e)

        return Response(branches)


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
    """
    Создание брони через партнёрский эндпоинт `/api/profigram/bookings/`.

    Пациент identifицируется по имени+фамилии+телефону — NewCRM сама находит
    существующего пациента по телефону или создаёт нового (дедуп на её стороне).
    """
    branch_id = serializers.IntegerField()
    employee_id = serializers.IntegerField()
    service_id = serializers.IntegerField()
    date = serializers.DateField(help_text="Дата записи, например 2026-09-27")
    time = serializers.TimeField(help_text="Время записи, например 15:30")
    patient_first_name = serializers.CharField(max_length=255)
    patient_last_name = serializers.CharField(max_length=255)
    patient_phone = serializers.CharField(max_length=32)

    def validate(self, attrs):
        naive = dt_datetime.combine(attrs["date"], attrs["time"])
        aware = dj_timezone.make_aware(naive)
        if aware <= dj_timezone.now():
            raise serializers.ValidationError("Дата и время записи должны быть в будущем.")
        return attrs


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
        description=(
            "Создает запись к указанному специалисту (employee_id) в NewCRM через "
            "партнёрский эндпоинт /api/profigram/bookings/. Пациент ищется по телефону "
            "и создаётся автоматически, если не найден. Цену определяет NewCRM по service_id."
        ),
        request=MamadocBookingCreateSerializer,
        responses={
            201: dict,
            400: {
                "description": "Не хватает полей, дата в прошлом, или NewCRM отклонила данные (например, несуществующий филиал/услугу/врача, либо занятый слот)",
                "examples": {
                    "past_date": {"value": {"nonFieldErrors": ["Дата и время записи должны быть в будущем."]}},
                    "missing_fields": {"value": {"branchId": ["Обязательное поле."], "patientPhone": ["Обязательное поле."]}},
                    "unknown_branch": {"value": {"detail": [{"msg": "branch: Филиал 999999 не найден.", "type": "value_error"}]}},
                    "slot_taken": {"value": {"code": "appointment_overlap", "message": "Время приёма пересекается с другим приёмом.", "requestedSlot": {"startsAt": "...", "endsAt": "..."}, "overlaps": [{"appointmentId": 123, "startsAt": "...", "endsAt": "...", "employeeId": 6, "employeeName": "...", "patientName": "..."}]}},
                },
            },
            401: {"description": "Нет токена или он недействителен", "example": {"detail": "Учетные данные не были предоставлены."}},
            403: {
                "description": "Не специалист, либо у ключа Профиграма нет права profigram.bookings.create в NewCRM",
                "examples": {
                    "not_specialist": {"value": {"detail": "У вас недостаточно прав для выполнения данного действия."}},
                    "no_newcrm_permission": {"value": {"detail": [{"msg": "Permission denied: profigram.bookings.create", "type": "security"}]}},
                },
            },
            502: {"description": "Сбой связи с NewCRM (сеть, сервер недоступен)", "example": {"detail": "Ошибка соединения с MamaDoc."}},
        },
        tags=["NewCRM Integration"],
    )
    def post(self, request):
        serializer = MamadocBookingCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        try:
            result = mamadoc_client.create_booking(
                branch_id=data["branch_id"],
                employee_id=data["employee_id"],
                service_id=data["service_id"],
                date=data["date"].isoformat(),
                time=data["time"].strftime("%H:%M"),
                first_name=data["patient_first_name"],
                last_name=data["patient_last_name"],
                phone=data["patient_phone"],
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
        description=(
            "Отменяет существующую запись по её ID через партнёрский эндпоинт "
            "/api/profigram/bookings/<id>/cancel/ (status -> canceled). Меняет только "
            "статус и причину отмены, больше ничего в приёме затронуть нельзя."
        ),
        request=MamadocBookingCancelSerializer,
        responses={
            200: dict,
            401: {"description": "Нет токена или он недействителен", "example": {"detail": "Учетные данные не были предоставлены."}},
            403: {
                "description": "Не специалист, либо у ключа Профиграма нет права profigram.bookings.create в NewCRM",
                "examples": {
                    "not_specialist": {"value": {"detail": "У вас недостаточно прав для выполнения данного действия."}},
                    "no_newcrm_permission": {"value": {"detail": [{"msg": "Permission denied: profigram.bookings.create", "type": "security"}]}},
                },
            },
            404: {
                "description": "Запись не найдена или принадлежит другой организации",
                "example": {"detail": [{"msg": "Приём не найден.", "type": "not_found"}]},
            },
            502: {"description": "Сбой связи с NewCRM (сеть, сервер недоступен)", "example": {"detail": "Ошибка соединения с MamaDoc."}},
        },
        tags=["NewCRM Integration"],
    )
    def patch(self, request, appointment_id):
        serializer = MamadocBookingCancelSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        reason = serializer.validated_data.get("reason", "")

        try:
            result = mamadoc_client.cancel_booking(appointment_id, reason=reason)
        except MamaDocAPIError as e:
            return _error_response(e)

        return Response(mamadoc_client.reformat_appointment_dates(result), status=status.HTTP_200_OK)
