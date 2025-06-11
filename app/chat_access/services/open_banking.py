import requests
import logging

from django.conf import settings

PAYMENT_API_URL = "https://pay.operator.kg/api/v1/payments/make-payment-link/"
PAYMENT_API_TOKEN = settings.PAYMENT_API_TOKEN

logger = logging.getLogger(__name__)


def generate_payment_link(access_order):
    payload = {
        "amount": str(access_order.price),
        "transaction_id": str(access_order.id),
        "comment": f"Оплата заказа #{access_order.id} hospital",
        "redirect_url": f"https://profigram.site/profigramlinks/specialist/{access_order.specialist_id}",
        'token': PAYMENT_API_TOKEN,
    }

    headers = {
        "Content-Type": "application/json",
    }

    try:
        response = requests.post(PAYMENT_API_URL, json=payload, headers=headers)

        if response.status_code == 200:
            data = response.json()
            return data.get('pay_url')
        else:
            logger.error(f"Ошибка создания платёжной ссылки. Код: {response.status_code}, Ответ: {response.content}")
            return None

    except Exception as e:
        logger.error(f"Ошибка при запросе к платежному сервису: {str(e)}", exc_info=True)
        return None
