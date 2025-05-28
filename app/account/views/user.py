from drf_spectacular.utils import extend_schema
from rest_framework import status, permissions, generics
from rest_framework.response import Response
from rest_framework.views import APIView
from django.contrib.auth import get_user_model

from .. import serializers
from ..serializers import ShowInSearchSerializer

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

