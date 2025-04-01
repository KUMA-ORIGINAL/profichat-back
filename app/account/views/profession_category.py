from drf_spectacular.utils import extend_schema
from rest_framework import viewsets, mixins

from ..models import ProfessionCategory
from ..serializers import ProfessionCategorySerializer


@extend_schema(
    tags=['Profession Category'],
)
class ProfessionCategoryViewSet(viewsets.GenericViewSet,
                                mixins.ListModelMixin,):
    queryset = ProfessionCategory.objects.filter(parent=None)
    serializer_class = ProfessionCategorySerializer
