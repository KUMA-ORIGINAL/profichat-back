import requests
import uuid
import logging

from django.conf import settings


logger = logging.getLogger(__name__)

def send_sms_code(phone, code):
    login = settings.SMS_LOGIN
    password = settings.SMS_PASSWORD
    sender = 'SMSPRO.KG'
    transactionId = str(uuid.uuid4().hex[:10])
    text = f'Ваш код подтверждения: {code}'

    xml_data = f"""<?xml version="1.0" encoding="UTF-8"?>
    <message>
        <login>{login}</login>
        <pwd>{password}</pwd>
        <id>{transactionId}</id>
        <sender>{sender}</sender>
        <text>{text}</text>
        <phones>
            <phone>{phone}</phone>
        </phones>
    </message>"""

    url = 'https://smspro.nikita.kg/api/message'
    headers = {'Content-Type': 'application/xml'}

    try:
        response = requests.post(url, data=xml_data.encode('utf-8'), headers=headers, timeout=10)

        if response.status_code != 200:
            logger.warning(f'Ошибка SMS. Статус: {response.status_code}. Ответ: {response.text}')
            return False

        logger.info(f'SMS успешно отправлено на номер {phone}')
        return True

    except Exception as e:
        logger.error(f'Ошибка при отправке SMS: {e}')
        return False