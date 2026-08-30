"""«Стать специалистом» по карточке сотрудника из ErkinAI.

Экран регистрации получает предложение в ответе `auth/sms/verify/`
(`erkinaiSpecialistOffer`) и, если человек нажал «да, это я», зовёт сюда с id
выбранной карточки и id организации из нашего справочника.

Почему это отдельный явный шаг, а не автоматика при регистрации: номера
операторы перевыпускают, и новый владелец номера уволившегося врача не должен
молча получить его профиль и привязку к чужой клинике. Роль специалиста
выдаётся только по осознанному нажатию.
"""

import logging

from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from account.models import Organization
from common.errors import ErrorCode, error_response
from integrations.erkinai import staff as erkinai_staff

logger = logging.getLogger(__name__)


@extend_schema(tags=["Auth"])
class ErkinAIBecomeSpecialistView(APIView):
    """POST `{"employeeId": 42, "organizationId": 7}` — принять карточку ErkinAI.

    `organizationId` — из нашего справочника (`GET /api/organizations/`), не из
    ErkinAI. Необязателен: без него роль выдаётся, а организацию человек
    выберет позже — блокировать привязку из-за того, что клиники нет в списке,
    незачем.
    """

    permission_classes = [IsAuthenticated]

    def post(self, request):
        employee_id = request.data.get("employee_id")
        if employee_id in (None, ""):
            return error_response(
                ErrorCode.PARAM_REQUIRED,
                "Не передан employeeId.",
                status.HTTP_400_BAD_REQUEST,
            )

        organization, error = self._resolve_organization(request.data)
        if error is not None:
            return error

        # Ищем заново по телефону САМОГО пользователя, а не доверяем
        # присланному id: иначе любой авторизованный клиент забрал бы себе
        # чужой профиль.
        card = erkinai_staff.find_card(request.user.phone_number, employee_id)
        if card is None:
            logger.info(
                "[ERKINAI] Пользователь %s просил карточку %s — не его или нет такой",
                request.user.id,
                employee_id,
            )
            return error_response(
                ErrorCode.NOT_FOUND,
                "Карточка сотрудника с таким номером телефона не найдена.",
                status.HTTP_404_NOT_FOUND,
            )

        user = erkinai_staff.apply_card(request.user, card, organization=organization)
        return Response(
            {
                "role": user.role,
                "organization_id": user.organization_id,
                "employee_id": card.get("id"),
            },
            status=status.HTTP_200_OK,
        )

    @staticmethod
    def _resolve_organization(data):
        """Организация из нашего справочника или ``(None, None)``.

        Возвращает пару ``(организация, ответ-ошибка)``. Несуществующая или
        погашенная — ошибка, а не молчаливое «привяжем без организации»:
        клиент выбирал из списка, и если выбор не прошёл, он должен об этом
        узнать, а не обнаружить пустое поле в профиле.
        """
        raw = data.get("organization_id")
        if raw in (None, ""):
            return None, None
        try:
            organization_id = int(raw)
        except (TypeError, ValueError):
            return None, error_response(
                ErrorCode.PARAM_INVALID,
                "organizationId должен быть числом.",
                status.HTTP_400_BAD_REQUEST,
            )
        organization = Organization.objects.filter(
            pk=organization_id, is_active=True
        ).first()
        if organization is None:
            return None, error_response(
                ErrorCode.NOT_FOUND,
                "Организация не найдена.",
                status.HTTP_404_NOT_FOUND,
            )
        return organization, None
