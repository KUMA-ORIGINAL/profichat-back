from drf_spectacular.utils import extend_schema, extend_schema_view
from rest_framework import viewsets, mixins
from rest_framework.permissions import IsAuthenticated
from ..models import Chat
from ..serializers import ChatListSerializer, ChatCreateSerializer


@extend_schema(tags=['Chats'])
@extend_schema_view(
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
    Доступен только авторизованным пользователям.
    """
    queryset = Chat.objects.all()
    permission_classes = [IsAuthenticated]

    def get_serializer_class(self):
        if self.action == 'create':
            return ChatCreateSerializer
        return ChatListSerializer

    def get_queryset(self):
        """
        Ограничиваем queryset только чатами, в которых участвует текущий пользователь.
        """
        user = self.request.user
        return Chat.objects.filter(client=user) | Chat.objects.filter(specialist=user)
