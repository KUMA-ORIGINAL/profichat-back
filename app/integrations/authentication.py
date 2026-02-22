import logging

from django.conf import settings
from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import AuthenticationFailed

logger = logging.getLogger(__name__)


class APIKeyUser:
    """Виртуальный пользователь для API-ключевой аутентификации."""

    is_authenticated = True
    is_active = True
    is_anonymous = False
    pk = None

    def __init__(self, service_name: str):
        self.service_name = service_name

    def __str__(self):
        return f"APIKeyUser({self.service_name})"


class MedCRMApiKeyAuthentication(BaseAuthentication):
    """
    Аутентификация по заголовку X-Api-Key для MedCRM.
    """

    HEADER = "HTTP_X_API_KEY"

    def authenticate(self, request):
        api_key = request.META.get(self.HEADER)
        if not api_key:
            return None

        expected_key = getattr(settings, "MEDCRM_API_KEY", None)
        if not expected_key:
            logger.error("MEDCRM_API_KEY not configured in settings")
            raise AuthenticationFailed("Сервис временно недоступен.")

        if api_key != expected_key:
            raise AuthenticationFailed("Неверный API-ключ.")

        return (APIKeyUser("medcrm"), None)
