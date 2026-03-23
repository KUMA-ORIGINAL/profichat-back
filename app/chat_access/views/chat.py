from django.db.models import Prefetch
from django.utils import timezone
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema, extend_schema_view, OpenApiParameter
from rest_framework import viewsets, mixins, exceptions
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from account.models import ROLE_SPECIALIST, ROLE_CLIENT
from account.models import InviteDelivery
from ..models import AccessOrder, Chat
from ..serializers import ChatListSerializer, ChatCreateSerializer, ChatUpdateSerializer
from ..services import (
    build_chat_list_item,
    create_or_get_chat,
    get_should_reply_map,
    update_chat_and_stream,
)


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
                  mixins.CreateModelMixin,
                  mixins.UpdateModelMixin):
    """
    ViewSet для чатов.
    """
    queryset = Chat.objects.all()
    permission_classes = [IsAuthenticated]

    def get_serializer_class(self):
        if self.action == 'create':
            return ChatCreateSerializer
        elif self.action in ['update', 'partial_update']:
            return ChatUpdateSerializer
        return ChatListSerializer

    def update(self, request, *args, **kwargs):
        if request.user.role != ROLE_SPECIALIST:
            raise exceptions.PermissionDenied("Только специалисты могут редактировать заметки")
        return super().update(request, *args, **kwargs)

    def list(self, request, *args, **kwargs):
        chats = list(self.get_queryset())
        should_reply_map = get_should_reply_map(chats, request.user)
        items = [build_chat_list_item(chat, request.user, should_reply_map) for chat in chats]

        page = self.paginate_queryset(items)
        if page is not None:
            serializer = ChatListSerializer(page, many=True)
            return self.get_paginated_response(serializer.data)

        serializer = ChatListSerializer(items, many=True)
        return Response(serializer.data)

    def perform_create(self, serializer):
        client = serializer.validated_data["client"]
        specialist = serializer.validated_data["specialist"]
        chat = create_or_get_chat(client=client, specialist=specialist)
        serializer.instance = chat

    def perform_update(self, serializer):
        update_chat_and_stream(serializer.instance, serializer.validated_data)

    def get_queryset(self):
        user = self.request.user
        access_status = self.request.query_params.get('access_status')

        if user.role == ROLE_SPECIALIST:
            base_qs = Chat.objects.filter(specialist=user)
        elif user.role == ROLE_CLIENT:
            base_qs = Chat.objects.filter(client=user)
        else:
            base_qs = Chat.objects.none()  # если роль не определена — ничего не возвращаем

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

        now = timezone.now()
        return base_qs.select_related("client", "specialist").prefetch_related(
            Prefetch(
                "invite_deliveries",
                queryset=InviteDelivery.objects.order_by("-created_at"),
                to_attr="prefetched_invite_deliveries",
            ),
            Prefetch(
                "access_orders",
                queryset=AccessOrder.objects.filter(
                    payment_status="success",
                    expires_at__gt=now,
                ).order_by("-created_at"),
                to_attr="prefetched_active_access_orders",
            ),
        )
