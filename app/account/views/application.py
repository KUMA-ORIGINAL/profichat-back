from rest_framework import viewsets, mixins
from rest_framework.permissions import IsAuthenticatedOrReadOnly

from ..models import Application
from ..serializers import ApplicationSerializer


class ApplicationCreateViewSet(viewsets.GenericViewSet,
                            mixins.CreateModelMixin):
    queryset = Application.objects.all()
    serializer_class = ApplicationSerializer
    permission_classes = (IsAuthenticatedOrReadOnly,)
