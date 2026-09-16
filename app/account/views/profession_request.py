from drf_spectacular.utils import extend_schema
from rest_framework import mixins, viewsets
from rest_framework.permissions import IsAuthenticated
from rest_framework.throttling import ScopedRateThrottle

from ..models import ProfessionRequest
from ..serializers import ProfessionRequestSerializer
from ..services.profession_request import create_profile_request


@extend_schema(tags=['Profession Category'])
class ProfessionRequestViewSet(mixins.CreateModelMixin,
                               mixins.ListModelMixin,
                               viewsets.GenericViewSet):
    """Заявки на профессию, которой нет в справочнике.

    `POST` — подать заявку из «Редактировать профиль»; доступно любой роли.
    `GET` — свои заявки со статусом и причиной отказа.
    """

    serializer_class = ProfessionRequestSerializer
    permission_classes = (IsAuthenticated,)
    throttle_scope = 'profession_requests'

    def get_throttles(self):
        # лимит только на подачу — просмотр своих заявок не ограничиваем
        if self.action == 'create':
            return [ScopedRateThrottle()]
        return []

    def get_queryset(self):
        return ProfessionRequest.objects.filter(user=self.request.user)

    def perform_create(self, serializer):
        serializer.instance = create_profile_request(
            user=self.request.user,
            name=serializer.validated_data['name'],
            description=serializer.validated_data['description'],
        )
