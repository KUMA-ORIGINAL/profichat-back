"""Push-уведомления, инициированные ErkinAI.

Обратное направление интеграции: обычно ProfiChat ходит в ErkinAI, здесь же
ErkinAI просит ProfiChat доставить push своему пользователю. Получатель
опознаётся по номеру телефона — единственному идентификатору, общему для
двух систем (тем же ключом работают SSO и приглашение клиента).

Ключ ``X-Api-Key`` авторизует вызывающую систему, не пользователя, поэтому
эндпоинт умышленно ничего не создаёт: нет пользователя ProfiChat с таким
номером — 404, а не тихая регистрация.

Ключ и класс аутентификации носят историческое имя ``MedCRM``: тот же секрет
уже используют ``/api/integration/medcrm/*``, и переименование переменной
окружения сломало бы развёртывание. Имя ключа — единственное, что осталось от
старого названия продукта.
"""

import logging
import re

from django.contrib.auth import get_user_model
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from account.models import Notification
from common.errors import ErrorCode, error_response
from common.notifications import notify_user
from integrations.medcrm.authentication import MedCRMApiKeyAuthentication
from integrations.medcrm.permissions import IsMedCRMAuthenticated
from integrations.serializers import (
    ErkinAIPushResponseSerializer,
    ErkinAIPushSerializer,
)

logger = logging.getLogger(__name__)
User = get_user_model()

_PHONE_NOISE = re.compile(r"[^\d+]")


def _phone_variants(raw):
    """Номер в тех видах, в которых он мог осесть в базе.

    ErkinAI отдаёт номер так, как его ввели в карточке: с пробелами, скобками
    или вовсе без «+». Полагаться на совпадение байт в байт нельзя, но и
    искать по «последним цифрам» опасно — так можно попасть в чужой аккаунт.
    Поэтому чистим разделители и допускаем только форму с «+» и без него.
    """
    digits = _PHONE_NOISE.sub("", raw or "")
    if not digits:
        return []
    plain = digits.lstrip("+")
    if not plain:
        return []
    return [f"+{plain}", plain]


class ErkinAIPushView(APIView):
    """Отправка push-уведомления пользователю ProfiChat по запросу ErkinAI."""

    authentication_classes = [MedCRMApiKeyAuthentication]
    permission_classes = [IsMedCRMAuthenticated]

    @extend_schema(
        summary="[ErkinAI] Отправить push-уведомление",
        description=(
            "Находит пользователя ProfiChat по номеру телефона, создаёт "
            "уведомление в его ленте и отправляет push на активные устройства. "
            "Ответ описывает результат доставки целиком: 200 приходит и тогда, "
            "когда устройств нет или FCM отклонил токен — смотрите `delivered` "
            "и `errorCode`, а не только HTTP-статус."
        ),
        request=ErkinAIPushSerializer,
        responses={200: ErkinAIPushResponseSerializer},
        tags=["ErkinAI Integration"],
    )
    def post(self, request):
        serializer = ErkinAIPushSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        variants = _phone_variants(data["phone_number"])
        user = (
            User.objects.filter(phone_number__in=variants, is_active=True).first()
            if variants
            else None
        )
        if not user:
            return error_response(
                ErrorCode.USER_NOT_FOUND,
                "Пользователь ProfiChat с таким номером не найден.",
                status.HTTP_404_NOT_FOUND,
            )

        external_id = (data.get("external_id") or "").strip()
        payload = {str(k): str(v) for k, v in (data.get("payload") or {}).items()}
        payload["type"] = Notification.TYPE_ERKINAI
        if external_id:
            payload["external_id"] = external_id
            duplicate = Notification.objects.filter(
                recipient=user,
                notification_type=Notification.TYPE_ERKINAI,
                payload__external_id=external_id,
            ).first()
            if duplicate is not None:
                # Повтор приходит, когда наш ответ не дошёл до ErkinAI: у неё
                # отправка осталась неподтверждённой, у нас — выполненной.
                # Второй push тут был бы дублем в шторке пользователя.
                logger.info(
                    "ErkinAI push: duplicate external_id=%s user_id=%s notification_id=%s",
                    external_id, user.id, duplicate.id,
                )
                return Response({
                    "notification_id": duplicate.id,
                    "delivered": duplicate.pushed_at is not None,
                    "device_count": 0,
                    "success_count": 0,
                    "error_code": "",
                    "error_message": "",
                    "duplicate": True,
                })

        result = notify_user(
            user=user,
            title=data["title"],
            message=data["body"],
            notification_type=Notification.TYPE_ERKINAI,
            payload=payload,
            log_prefix="[Push][ErkinAI]",
            return_meta=True,
        )

        logger.info(
            "ErkinAI push: user_id=%s external_id=%s delivered=%s devices=%s code=%s",
            user.id,
            external_id or "-",
            result.get("ok"),
            result.get("device_count"),
            result.get("error_code") or "-",
        )

        return Response({
            "notification_id": result.get("notification_id"),
            "delivered": bool(result.get("ok")),
            "device_count": result.get("device_count", 0),
            "success_count": result.get("success_count", 0),
            "error_code": result.get("error_code", ""),
            "error_message": result.get("error_message", ""),
            "duplicate": False,
        })
