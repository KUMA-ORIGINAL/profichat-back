from rest_framework import viewsets, mixins

from ..models import Application
from ..serializers import ApplicationSerializer


class ApplicationCreateViewSet(viewsets.GenericViewSet,
                            mixins.CreateModelMixin):
    queryset = Application.objects.all()
    serializer_class = ApplicationSerializer
