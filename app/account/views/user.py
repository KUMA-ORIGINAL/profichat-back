import random

from drf_spectacular.utils import extend_schema
from rest_framework import status, permissions, generics
from rest_framework.response import Response
from rest_framework.views import APIView
from django.contrib.auth import get_user_model
from rest_framework_simplejwt.tokens import RefreshToken

from .. import serializers
from ..models.otp import OTP
from ..sms import send_sms_code

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


@extend_schema(tags=['Auth'])
class RegisterView(APIView):
    serializer_class = serializers.RegisterSerializer

    def post(self, request):
        phone_number = request.data.get("phone_number")
        password = request.data.get("password")

        if User.objects.filter(phone_number=phone_number).exists():
            return Response({"error": "Этот номер уже зарегистрирован"}, status=status.HTTP_400_BAD_REQUEST)

        user = User.objects.create_user(phone_number=phone_number, password=password)
        user.create_stream_user()  # Создание в Stream Chat
        return Response(serializers.UserSerializer(user).data, status=status.HTTP_201_CREATED)

    # def post(self, request):
    #     serializer = self.serializer_class(data=request.data)
    #     if serializer.is_valid():
    #         phone_number = serializer.validated_data.get("phone_number")
    #         # name = serializer.validated_data.get("name")
    #
    #         if User.objects.filter(phone_number=phone_number).exists():
    #             return Response({"error": "Этот номер уже зарегистрирован"}, status=status.HTTP_400_BAD_REQUEST)
    #
    #         # user = User.objects.create_user(phone_number=phone_number)
    #         # user.is_active = False
    #         # user.save()
    #
    #         code = str(random.randint(1000, 9999))
    #         OTP.objects.create(phone_number=phone_number, code=code)
    #
    #         if send_sms_code(phone_number, code):
    #             return Response({"message": "Код подтверждения отправлен"}, status=status.HTTP_201_CREATED)
    #         else:
    #             return Response({"error": "Не удалось отправить SMS"}, status=500)
    #
    #     return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@extend_schema(tags=['Auth'])
class LoginView(APIView):
    serializer_class = serializers.LoginSerializer

    def post(self, request):
        serializer = self.serializer_class(data=request.data)
        if serializer.is_valid():
            user = serializer.validated_data["user"]
            refresh = RefreshToken.for_user(user)  # Генерируем JWT
            return Response({
                "refresh": str(refresh),
                "access": str(refresh.access_token),
            })
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@extend_schema(tags=['Auth'])
class VerifyOTPView(APIView):
    serializer_class = serializers.VerifyOTPSerializer

    def post(self, request):
        serializer = self.serializer_class(data=request.data)
        if serializer.is_valid():
            phone_number = serializer.validated_data.get("phone_number")
            code = serializer.validated_data.get("code")

            try:
                otp = OTP.objects.filter(phone_number=phone_number, code=code, is_verified=False).latest('created_at')

                if otp.is_expired():
                    return Response({"error": "Код истек"}, status=400)

                otp.is_verified = True
                otp.save()

                user = User.objects.get(phone_number=phone_number)
                user.is_active = True
                user.save()

                return Response({"message": "Пользователь подтвержден", "user": serializers.UserMeSerializer(user).data}, status=200)

            except OTP.DoesNotExist:
                return Response({"error": "Неверный код"}, status=400)
            except User.DoesNotExist:
                return Response({"error": "Пользователь не найден"}, status=404)

        return Response(serializer.errors, status=400)