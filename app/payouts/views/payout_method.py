from rest_framework import viewsets, mixins

from ..models import PayoutMethod
from ..serializers import PayoutMethodSerializer


class PayoutMethodViewSet(viewsets.GenericViewSet,
                          mixins.ListModelMixin):
    queryset = PayoutMethod.objects.filter(is_active=True)
    serializer_class = PayoutMethodSerializer
