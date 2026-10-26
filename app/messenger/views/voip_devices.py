from drf_spectacular.utils import extend_schema
from rest_framework import serializers, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from messenger.models import VoipDevice


class VoipDeviceSerializer(serializers.ModelSerializer):
    class Meta:
        model = VoipDevice
        fields = ("token", "bundle_id", "active")
        read_only_fields = ("active",)
        # уникальность проверяет update_or_create: тот же токен перепривязывается к текущему пользователю
        extra_kwargs = {"token": {"validators": []}}


@extend_schema(tags=["Messenger"])
class VoipDevicesView(APIView):
    """Регистрация PushKit-токена iOS для VoIP-пушей о входящих звонках."""

    permission_classes = [IsAuthenticated]

    @extend_schema(
        summary="Register VoIP (PushKit) token",
        request=VoipDeviceSerializer,
        responses={200: VoipDeviceSerializer, 201: VoipDeviceSerializer},
    )
    def post(self, request):
        serializer = VoipDeviceSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        device, created = VoipDevice.objects.update_or_create(
            token=data["token"],
            defaults={"user": request.user, "bundle_id": data["bundle_id"], "active": True},
        )
        return Response(
            VoipDeviceSerializer(device).data,
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )


@extend_schema(tags=["Messenger"])
class VoipDeviceDetailView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(summary="Unregister VoIP (PushKit) token", request=None, responses={204: None})
    def delete(self, request, token):
        # идемпотентно; чужой токен не трогаем
        VoipDevice.objects.filter(user=request.user, token=token).delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
