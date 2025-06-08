import random

from django.contrib.auth import get_user_model
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenRefreshView

from ..models import OTP
from account import serializers
from ..services import send_sms


User = get_user_model()


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


@extend_schema(tags=["Auth"])
class CustomTokenRefreshView(TokenRefreshView):
    """Обновление access токена по refresh токену"""
    pass


@extend_schema(tags=['Auth'])
class RegisterView(APIView):
    serializer_class = serializers.PhoneNumberSerializer

    def post(self, request):
        serializer = self.serializer_class(data=request.data)
        if serializer.is_valid():
            phone_number = serializer.validated_data.get("phone_number")

            existing_user = User.objects.filter(phone_number=phone_number).first()
            if existing_user and existing_user.is_active:
                return Response({"error": "Этот номер уже зарегистрирован"}, status=status.HTTP_400_BAD_REQUEST)

            code = str(random.randint(1000, 9999))
            otp = OTP.objects.create(phone_number=phone_number, code=code)

            text = f"Profichat\nКод подтверждения: {code}. Никому не сообщайте его."
            if send_sms(phone=phone_number, text=text, transaction_id=otp.id):
                return Response({"message": "Код подтверждения отправлен"}, status=status.HTTP_201_CREATED)
            else:
                return Response({"error": "Не удалось отправить SMS"}, status=500)

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@extend_schema(tags=['Auth'])
class VerifyOTPView(APIView):
    serializer_class = serializers.VerifyOTPWithUserSerializer

    def post(self, request):
        serializer = self.serializer_class(data=request.data)
        if serializer.is_valid():
            phone_number = serializer.validated_data.get("phone_number")
            code = serializer.validated_data.get("code")
            password = serializer.validated_data.get("password")
            first_name = serializer.validated_data.get("first_name")
            last_name = serializer.validated_data.get("last_name")

            try:
                otp = OTP.objects.filter(phone_number=phone_number, code=code, is_verified=False).latest('created_at')

                if otp.is_expired():
                    return Response({"error": "Код истек"}, status=400)

                otp.is_verified = True
                otp.save()

                existing_user = User.objects.filter(phone_number=phone_number).first()

                if existing_user:
                    if existing_user.is_active:
                        return Response({"error": "Пользователь уже существует"}, status=400)
                    else:
                        existing_user.first_name = first_name
                        existing_user.last_name = last_name
                        existing_user.set_password(password)
                        existing_user.is_active = True
                        existing_user.save()

                        return Response({
                            "message": "Пользователь подтвержден и активирован",
                            "user": serializers.UserMeSerializer(existing_user).data
                        }, status=200)

                user = User.objects.create_user(
                    phone_number=phone_number,
                    first_name=first_name,
                    last_name=last_name,
                    password=password,
                )

                return Response({
                    "message": "Пользователь создан и подтвержден",
                    "user": serializers.UserMeSerializer(user).data
                }, status=200)

            except OTP.DoesNotExist:
                return Response({"error": "OTP не найден"}, status=400)
            except User.DoesNotExist:
                return Response({"error": "Пользователь не найден"}, status=404)

        return Response(serializer.errors, status=400)


@extend_schema(tags=['Auth'])
class PasswordResetRequestView(APIView):
    serializer_class = serializers.PhoneNumberSerializer

    def post(self, request):
        serializer = self.serializer_class(data=request.data)
        if serializer.is_valid():
            phone_number = serializer.validated_data['phone_number']

            try:
                user = User.objects.get(phone_number=phone_number)
            except User.DoesNotExist:
                return Response({"error": "Пользователь не найден"}, status=404)

            code = str(random.randint(1000, 9999))
            OTP.objects.create(phone_number=phone_number, code=code)

            text = f"Profichat\nКод для сброса пароля: {code}. Никому не сообщайте его."
            if send_sms(phone=phone_number, text=text):
                return Response({"message": "Код отправлен на номер"}, status=200)
            else:
                return Response({"error": "Не удалось отправить SMS"}, status=500)

        return Response(serializer.errors, status=400)


@extend_schema(tags=['Auth'])
class PasswordResetVerifyView(APIView):
    serializer_class = serializers.VerifyOTPSerializer

    def post(self, request):
        serializer = self.serializer_class(data=request.data)
        if serializer.is_valid():
            phone_number = serializer.validated_data['phone_number']
            code = serializer.validated_data['code']

            try:
                otp = OTP.objects.filter(phone_number=phone_number, code=code, is_verified=False).latest('created_at')

                if otp.is_expired():
                    return Response({"error": "Код истёк"}, status=400)

                otp.is_verified = True
                otp.save()

                return Response({"message": "Код подтверждён"}, status=200)
            except OTP.DoesNotExist:
                return Response({"error": "Неверный код"}, status=400)

        return Response(serializer.errors, status=400)


@extend_schema(tags=['Auth'])
class PasswordResetConfirmView(APIView):
    serializer_class = serializers.PasswordResetConfirmSerializer  # phone_number, code, new_password

    def post(self, request):
        serializer = self.serializer_class(data=request.data)
        if serializer.is_valid():
            phone_number = serializer.validated_data['phone_number']
            code = serializer.validated_data['code']
            new_password = serializer.validated_data['new_password']

            try:
                otp = OTP.objects.filter(phone_number=phone_number, code=code, is_verified=True).latest('created_at')
                user = User.objects.get(phone_number=phone_number)

                user.set_password(new_password)
                user.save()

                return Response({"message": "Пароль успешно сброшен"}, status=200)
            except OTP.DoesNotExist:
                return Response({"error": "Код не подтверждён"}, status=400)
            except User.DoesNotExist:
                return Response({"error": "Пользователь не найден"}, status=404)

        return Response(serializer.errors, status=400)
