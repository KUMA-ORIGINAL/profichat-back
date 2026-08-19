from rest_framework import viewsets, status
from rest_framework.response import Response
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt

from ..models import AccessOrder
import logging

from ..services import update_chat_data_from_order
from common.notifications import send_payment_success_push
from common.errors import ErrorCode, error_response

logger = logging.getLogger(__name__)


@method_decorator(csrf_exempt, name='dispatch')  # отключаем CSRF
class PaymentWebhookViewSet(viewsets.ViewSet):
    """
    ViewSet для обработки webhook от платёжной системы.
    """

    def create(self, request, *args, **kwargs):
        try:
            payload = request.data

            order_id = payload.get('operation_id')  # Идентификатор заказа
            new_payment_status = payload.get('operation_state')  # Новый статус оплаты

            logger.info(
                "Получен webhook: operation_id=%s operation_state=%s",
                order_id,
                new_payment_status,
            )

            if not order_id or not new_payment_status:
                logger.warning(
                    "Недостаточно данных в webhook: operation_id=%s operation_state=%s",
                    order_id,
                    new_payment_status,
                )
                return error_response(
                    ErrorCode.PARAM_REQUIRED,
                    'Недостаточно данных',
                    status.HTTP_400_BAD_REQUEST,
                    error='Недостаточно данных',
                )

            try:
                access_order = AccessOrder.objects.get(id=order_id)
            except AccessOrder.DoesNotExist:
                logger.error(f"Заказ доступа не найден: ID {order_id}")
                return error_response(
                    ErrorCode.ORDER_NOT_FOUND,
                    'Заказ не найден',
                    status.HTTP_404_NOT_FOUND,
                    error='Заказ не найден',
                )

            current_status = access_order.payment_status

            if current_status != new_payment_status:
                logger.info(f"Обновление статуса заказа {access_order.id}: {current_status} → {new_payment_status}")
                access_order.payment_status = new_payment_status
                access_order.save(update_fields=["payment_status"])

                if new_payment_status == 'success':
                    access_order.activate()

                    if access_order.chat:
                        update_chat_data_from_order(access_order)

                    specialist = access_order.specialist
                    specialist.balance += access_order.price
                    specialist.save(update_fields=["balance"])

                    send_payment_success_push(access_order.client, access_order)
            else:
                logger.info(f"Повторный webhook: статус уже установлен — {new_payment_status}")

            return Response({'success': True}, status=status.HTTP_200_OK)

        except Exception as e:
            logger.exception("Ошибка при обработке webhook")
            return error_response(
                ErrorCode.INTERNAL_ERROR,
                'Внутренняя ошибка',
                status.HTTP_500_INTERNAL_SERVER_ERROR,
                error='Внутренняя ошибка',
            )
