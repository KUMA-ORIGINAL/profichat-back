import requests
import uuid
import logging
from typing import Optional
from django.conf import settings
from xml.etree import ElementTree as ET

logger = logging.getLogger(__name__)

SMS_LOGIN = settings.SMS_LOGIN
SMS_PASSWORD = settings.SMS_PASSWORD
SMS_SENDER = settings.SMS_SENDER
SMS_API_URL = 'https://smspro.nikita.kg/api/message'
SMS_TIMEOUT = 10  # секунд


def send_sms(
    phone: str,
    text: str,
    transaction_id: Optional[str] = None,
    test: bool = False,
    return_meta: bool = False,
):
    transaction_id = transaction_id or uuid.uuid4().hex[:10]

    xml_data = f"""<?xml version="1.0" encoding="UTF-8"?>
    <message>
        <login>{SMS_LOGIN}</login>
        <pwd>{SMS_PASSWORD}</pwd>
        <id>{transaction_id}</id>
        <sender>{SMS_SENDER}</sender>
        <text>{text}</text>
        <phones>
            <phone>{phone}</phone>
        </phones>
        {'<test>1</test>' if test else ''}
    </message>"""

    headers = {'Content-Type': 'application/xml'}

    try:
        response = requests.post(
            SMS_API_URL,
            data=xml_data.encode('utf-8'),
            headers=headers,
            timeout=SMS_TIMEOUT
        )

        if response.status_code != 200:
            logger.warning(f"[SMS ERROR] Статус: {response.status_code}, Ответ: {response.text}, Телефон: {phone}")
            result = False
            if return_meta:
                return {
                    "ok": result,
                    "status_code": response.status_code,
                    "provider_status": "",
                    "provider_message_id": "",
                    "provider_response": response.text,
                    "transaction_id": transaction_id,
                    "error_message": f"HTTP {response.status_code}",
                }
            return result

        try:
            parsed = parse_sms_response(response.text)
            if parsed is None:
                logger.error("Ошибка разбора XML")
                if return_meta:
                    return {
                        "ok": False,
                        "status_code": response.status_code,
                        "provider_status": "",
                        "provider_message_id": "",
                        "provider_response": response.text,
                        "transaction_id": transaction_id,
                        "error_message": "Ошибка разбора XML",
                    }
                return False

            if parsed['status'] != '0':
                logger.warning(f"[SMS API ERROR] Статус: {parsed['status']}, Телефон: {phone}")
                if return_meta:
                    return {
                        "ok": False,
                        "status_code": response.status_code,
                        "provider_status": parsed.get("status") or "",
                        "provider_message_id": parsed.get("id") or "",
                        "provider_response": response.text,
                        "transaction_id": transaction_id,
                        "error_message": "Провайдер вернул ошибку",
                    }
                return False

            logger.info(f"[SMS OK] Сообщение отправлено на {phone}, ID: {parsed['id']}")
            if return_meta:
                return {
                    "ok": True,
                    "status_code": response.status_code,
                    "provider_status": parsed.get("status") or "",
                    "provider_message_id": parsed.get("id") or "",
                    "provider_response": response.text,
                    "transaction_id": transaction_id,
                    "error_message": "",
                }
            return True
        except ET.ParseError:
            logger.error(f"[SMS PARSE ERROR] Невозможно разобрать XML-ответ: {response.text}")
            if return_meta:
                return {
                    "ok": False,
                    "status_code": response.status_code,
                    "provider_status": "",
                    "provider_message_id": "",
                    "provider_response": response.text,
                    "transaction_id": transaction_id,
                    "error_message": "Невозможно разобрать XML",
                }
            return False

    except requests.RequestException as e:
        logger.error(f"[SMS EXCEPTION] Ошибка при отправке SMS на {phone}: {e}")
        if return_meta:
            return {
                "ok": False,
                "status_code": None,
                "provider_status": "",
                "provider_message_id": "",
                "provider_response": "",
                "transaction_id": transaction_id,
                "error_message": str(e),
            }
        return False

def parse_sms_response(xml_text: str):
    try:
        root = ET.fromstring(xml_text)
        # Учитываем namespace
        ns = {'ns': root.tag.split('}')[0].strip('{')}

        status = root.findtext('ns:status', namespaces=ns)
        message_id = root.findtext('ns:id', namespaces=ns)
        phones = root.findtext('ns:phones', namespaces=ns)
        smscnt = root.findtext('ns:smscnt', namespaces=ns)

        return {
            'status': status,
            'id': message_id,
            'phones': phones,
            'smscnt': smscnt
        }
    except ET.ParseError:
        return None
