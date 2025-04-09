from drf_spectacular.utils import extend_schema
from rest_framework import viewsets, permissions, mixins

from ..models import WorkSchedule
from ..serializers import WorkScheduleSerializer


@extend_schema(tags=['Work Schedule'])
class WorkScheduleViewSet(viewsets.GenericViewSet,
                          mixins.ListModelMixin,
                          mixins.CreateModelMixin,
                          mixins.UpdateModelMixin):
    serializer_class = WorkScheduleSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return WorkSchedule.objects.filter(user=self.request.user)
