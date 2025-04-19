from drf_spectacular.utils import extend_schema
from rest_framework import viewsets, permissions, mixins, status
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response

from ..models import WorkSchedule
from ..serializers import WorkScheduleSerializer


@extend_schema(tags=['Work Schedule'])
class WorkScheduleViewSet(viewsets.GenericViewSet,
                          mixins.ListModelMixin,
                          mixins.UpdateModelMixin):
    serializer_class = WorkScheduleSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return WorkSchedule.objects.filter(user=self.request.user)

    def create(self, request, *args, **kwargs):
        is_many = isinstance(request.data, list)
        serializer = self.get_serializer(data=request.data, many=is_many)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    def perform_create(self, serializer):
        serializer.save()

    @action(detail=False, methods=['put', 'patch'], url_path='bulk-update')
    def bulk_update(self, request):
        if not isinstance(request.data, list):
            raise ValidationError("Expected a list of items for bulk update.")

        updated_items = []
        errors = []

        for item_data in request.data:
            try:
                instance = WorkSchedule.objects.get(id=item_data['id'], user=request.user)
                serializer = self.get_serializer(instance, data=item_data, partial=request.method == 'PATCH')
                serializer.is_valid(raise_exception=True)
                serializer.save()
                updated_items.append(serializer.data)
            except Exception as e:
                errors.append({'id': item_data.get('id'), 'error': str(e)})

        return Response({'updated': updated_items, 'errors': errors})