from django.db.models import Q
from django.utils import timezone
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema, extend_schema_view, OpenApiParameter
from rest_framework import viewsets, mixins
from rest_framework.permissions import IsAuthenticated
from ..models import Chat
from ..serializers import ChatListSerializer, ChatCreateSerializer


@extend_schema(tags=['Chats'])
@extend_schema_view(
    list=extend_schema(
        summary='Список чатов',
        description='Возвращает все чаты, в которых участвует текущий пользователь. '
                    'Если пользователь — клиент, можно фильтровать по доступу через параметр `access_status`.',
        parameters=[
            OpenApiParameter(
                name='access_status',
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                required=False,
                description='Фильтрация по доступу клиента к чату:\n'
                            '`active` — только активные чаты\n'
                            '`inactive` — только неактивные чаты\n'
                            'Работает только для чатов, где пользователь — клиент.',
                enum=['active', 'inactive'],
            )
        ]
    ),
    create=extend_schema(
        summary='Создание чата',
        description='При создании чата, client автоматически поставится. '
                    'Кто отправил запрос, тот и клиент'
    )
)
class ChatViewSet(viewsets.GenericViewSet,
                  mixins.ListModelMixin,
                  mixins.CreateModelMixin):
    """
    ViewSet для чатов.
    """
    queryset = Chat.objects.all()
    permission_classes = [IsAuthenticated]

    def get_serializer_class(self):
        if self.action == 'create':
            return ChatCreateSerializer
        return ChatListSerializer

    def get_queryset(self):
        user = self.request.user
        access_status = self.request.query_params.get('access_status')

        base_qs = Chat.objects.filter(Q(client=user) | Q(specialist=user)).distinct()

        if access_status == 'active':
            return base_qs.filter(
                client=user,
                access_orders__payment_status='success',
                access_orders__expires_at__gt=timezone.now()
            ).distinct()

        elif access_status == 'inactive':
            return base_qs.filter(client=user).exclude(
                access_orders__payment_status='success',
                access_orders__expires_at__gt=timezone.now()
            ).distinct()

        return base_qs
