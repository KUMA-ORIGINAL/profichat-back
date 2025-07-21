from drf_spectacular.utils import extend_schema
from rest_framework import status, permissions, generics
from rest_framework.response import Response
from rest_framework.views import APIView
from django.contrib.auth import get_user_model

from .. import serializers
from ..serializers import ShowInSearchSerializer, InviteGreetingSerializer

User = get_user_model()


@extend_schema(tags=['Users Me'])
class UserMeViewSet(generics.RetrieveUpdateAPIView):
    queryset = User.objects.all()
    permission_classes  = (permissions.IsAuthenticated,)

    def get_serializer_class(self):
        if self.request.method in ['PUT', 'PATCH']:
            return serializers.UserMeUpdateSerializer
        return serializers.UserMeSerializer

    def get_object(self):
        return self.request.user

    @extend_schema(
        summary='Деактивация профиля (псевдо-удаление)',
        description='Помечает профиль пользователя как неактивный (is_active=False).',
        responses={204: None}
    )
    def delete(self, request, *args, **kwargs):
        user = self.get_object()
        user.is_active = False
        user.old_phone_number = user.phone_number
        user.phone_number = None
        user.save(update_fields=['is_active', 'phone_number', 'old_phone_number'])
        return Response(status=status.HTTP_204_NO_CONTENT)


@extend_schema(tags=['Users Me'])
class UpdateShowInSearchView(APIView):
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = ShowInSearchSerializer

    def patch(self, request):
        user = request.user
        serializer = self.serializer_class(user, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response({'detail': 'Поле "show_in_search" обновлено успешно.'}, status=status.HTTP_200_OK)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@extend_schema(tags=['Users Me'])
class UpdateInviteGreetingView(APIView):
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = InviteGreetingSerializer

    def patch(self, request):
        user = request.user
        serializer = self.serializer_class(user, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response({'detail': 'Поле "invite_greeting" обновлено успешно.'}, status=status.HTTP_200_OK)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
