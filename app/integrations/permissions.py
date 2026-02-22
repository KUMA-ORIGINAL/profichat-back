from rest_framework.permissions import BasePermission

from integrations.authentication import APIKeyUser


class IsMedCRMAuthenticated(BasePermission):
    """Доступ только для аутентифицированных MedCRM-запросов."""

    def has_permission(self, request, view):
        return isinstance(request.user, APIKeyUser) and request.user.service_name == "medcrm"
