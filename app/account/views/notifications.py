from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from push_notifications.models import GCMDevice
from drf_spectacular.utils import extend_schema, OpenApiResponse

from ..serializers import RegisterFCMTokenSerializer


class RegisterFCMTokenView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        request=RegisterFCMTokenSerializer,
        responses={
            200: OpenApiResponse(description="Token registered successfully"),
            400: OpenApiResponse(description="Missing or invalid data"),
        },
        summary="Register FCM token",
        description="Привязывает FCM токен к авторизованному пользователю"
    )
    def post(self, request):
        serializer = RegisterFCMTokenSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        reg_id = serializer.validated_data["registration_id"]

        device, created = GCMDevice.objects.update_or_create(
            registration_id=reg_id,
            defaults={"user": request.user, "active": True}
        )
        return Response({"status": "success", "created": created})
