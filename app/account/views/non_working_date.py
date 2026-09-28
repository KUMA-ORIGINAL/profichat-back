from django.db import transaction
from drf_spectacular.utils import extend_schema
from rest_framework import mixins, permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from ..models import NonWorkingDate
from ..serializers import NonWorkingDateSerializer, NonWorkingDateSyncSerializer
from ..services import broadcast_user_update


@extend_schema(tags=['Work Schedule'])
class NonWorkingDateViewSet(viewsets.GenericViewSet,
                            mixins.ListModelMixin,
                            mixins.DestroyModelMixin):
    """Нерабочие даты вне недельного графика.

    `GET` — предстоящие даты (начиная с сегодняшней).
    `POST` — отметить одну дату; повторная отметка той же даты не создаёт дубль.
    `DELETE /{id}/` — снять отметку.
    `PUT /sync/` — заменить все предстоящие даты переданным списком.
    """

    serializer_class = NonWorkingDateSerializer
    permission_classes = [permissions.IsAuthenticated]
    pagination_class = None

    def get_queryset(self):
        return NonWorkingDate.objects.filter(user=self.request.user).upcoming()

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        instance, created = NonWorkingDate.objects.get_or_create(
            user=request.user,
            date=serializer.validated_data['date'],
        )
        if created:
            broadcast_user_update(request.user, changes=["non_working_dates"])
        return Response(
            self.get_serializer(instance).data,
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )

    def perform_destroy(self, instance):
        instance.delete()
        broadcast_user_update(self.request.user, changes=["non_working_dates"])

    @extend_schema(request=NonWorkingDateSyncSerializer, responses=NonWorkingDateSerializer(many=True))
    @action(detail=False, methods=['put'], url_path='sync')
    def sync(self, request):
        serializer = NonWorkingDateSyncSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        dates = serializer.validated_data['dates']

        with transaction.atomic():
            upcoming = self.get_queryset()
            existing = set(upcoming.values_list('date', flat=True))
            upcoming.exclude(date__in=dates).delete()
            NonWorkingDate.objects.bulk_create([
                NonWorkingDate(user=request.user, date=date)
                for date in dates if date not in existing
            ])

        if existing != set(dates):
            broadcast_user_update(request.user, changes=["non_working_dates"])

        return Response(self.get_serializer(self.get_queryset(), many=True).data)
