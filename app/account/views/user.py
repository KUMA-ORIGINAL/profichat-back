import logging

from drf_spectacular.utils import extend_schema
from rest_framework import status, permissions, generics
from rest_framework.response import Response
from rest_framework.views import APIView
from django.contrib.auth import get_user_model

from .. import serializers
from ..serializers import (
    CanCallSerializer,
    InviteGreetingSerializer,
    NotifyOutsideWorkHoursSerializer,
    ShowInSearchSerializer,
)
from ..services import broadcast_user_update
from ..services.quiet_hours import sync_quiet_hours
from common.errors import ErrorCode, error_response

logger = logging.getLogger(__name__)

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

    def perform_update(self, serializer):
        user = serializer.save()
        broadcast_user_update(
            user,
            changes=serializer.validated_data.keys(),
        )

    @extend_schema(
        summary='Деактивация профиля (псевдо-удаление)',
        description='Помечает профиль пользователя как неактивный (is_active=False).',
        responses={204: None}
    )
    def delete(self, request, *args, **kwargs):
        user = self.get_object()
        user.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


@extend_schema(tags=['Users Me'])
class UpdateShowInSearchView(APIView):
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = ShowInSearchSerializer

    def get(self, request, format=None):
        user = request.user
        serializer = self.serializer_class(user)
        return Response(serializer.data, status=status.HTTP_200_OK)

    def patch(self, request):
        user = request.user
        serializer = self.serializer_class(user, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            broadcast_user_update(
                user,
                changes=serializer.validated_data.keys(),
            )
            return Response({'detail': 'Поле "show_in_search" обновлено успешно.'}, status=status.HTTP_200_OK)
        return error_response(
            ErrorCode.VALIDATION_ERROR,
            "Некорректные данные",
            status.HTTP_400_BAD_REQUEST,
            errors=serializer.errors,
            **serializer.errors,
        )


@extend_schema(tags=['Users Me'])
class UpdateInviteGreetingView(APIView):
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = InviteGreetingSerializer

    def patch(self, request):
        user = request.user
        serializer = self.serializer_class(user, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            broadcast_user_update(
                user,
                changes=serializer.validated_data.keys(),
            )
            return Response({'detail': 'Поле "invite_greeting" обновлено успешно.'}, status=status.HTTP_200_OK)
        return error_response(
            ErrorCode.VALIDATION_ERROR,
            "Некорректные данные",
            status.HTTP_400_BAD_REQUEST,
            errors=serializer.errors,
            **serializer.errors,
        )


@extend_schema(tags=['Users Me'])
class UpdateCanCallView(APIView):
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = CanCallSerializer

    def get(self, request, format=None):
        user = request.user
        serializer = self.serializer_class(user)
        return Response(serializer.data, status=status.HTTP_200_OK)

    def patch(self, request):
        user = request.user
        serializer = self.serializer_class(user, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            broadcast_user_update(
                user,
                changes=serializer.validated_data.keys(),
            )
            return Response({'detail': 'Поле обновлено успешно.'}, status=status.HTTP_200_OK)
        return error_response(
            ErrorCode.VALIDATION_ERROR,
            "Некорректные данные",
            status.HTTP_400_BAD_REQUEST,
            errors=serializer.errors,
            **serializer.errors,
        )


@extend_schema(tags=['Users Me'])
class UpdateNotifyOutsideWorkHoursView(APIView):
    """Уведомления в нерабочее время.

    `false` (по умолчанию) — вне графика пуши чата не приходят, в начале смены
    приходит сводка пропущенного. `true` — пуши приходят всегда.
    """

    permission_classes = [permissions.IsAuthenticated]
    serializer_class = NotifyOutsideWorkHoursSerializer

    def get(self, request, format=None):
        return Response(self.serializer_class(request.user).data, status=status.HTTP_200_OK)

    def patch(self, request):
        user = request.user
        serializer = self.serializer_class(user, data=request.data, partial=True)
        if not serializer.is_valid():
            return error_response(
                ErrorCode.VALIDATION_ERROR,
                "Некорректные данные",
                status.HTTP_400_BAD_REQUEST,
                errors=serializer.errors,
                **serializer.errors,
            )
        serializer.save()
        # Сразу, не дожидаясь планировщика: включил «всегда» посреди ночи —
        # пуши должны пойти уже сейчас, выключил — тишина начнётся тоже сейчас.
        try:
            sync_quiet_hours(user)
        except Exception:
            logger.exception("[QuietHours] Sync after settings change failed for user_id=%s", user.id)
        broadcast_user_update(user, changes=serializer.validated_data.keys())
        return Response(serializer.data, status=status.HTTP_200_OK)
