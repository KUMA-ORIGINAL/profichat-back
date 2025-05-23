from rest_framework import viewsets
from rest_framework.permissions import IsAuthenticated
from ..models import Chat
from ..serializers import ChatSerializer


class ChatViewSet(viewsets.ReadOnlyModelViewSet):
    """
    ViewSet только для чтения чатов.
    Доступен только авторизованным пользователям.
    """
    queryset = Chat.objects.all()
    serializer_class = ChatSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        """
        Ограничиваем queryset только чатами, в которых участвует текущий пользователь.
        """
        user = self.request.user
        return Chat.objects.filter(client=user) | Chat.objects.filter(specialist=user)
