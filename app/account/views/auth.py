import logging
import random
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone
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

logger = logging.getLogger(__name__)


@extend_schema(tags=["Auth"])
class CustomTokenRefreshView(TokenRefreshView):
    """Обновление access токена по refresh токену"""
    pass


@extend_schema(tags=['Auth'])
class SendSMSCodeView(APIView):
    serializer_class = serializers.PhoneNumberSerializer

    def post(self, request):
        serializer = self.serializer_class(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        phone_number = serializer.validated_data.get("phone_number")

        try:
            with transaction.atomic():
                OTP.objects.filter(
                    phone_number=phone_number,
                    created_at__lt=timezone.now() - timedelta(hours=1)
                ).delete()

                code = str(random.randint(1000, 9999))
                otp = OTP.objects.create(
                    phone_number=phone_number,
                    code=code
                )
                logger.info(f"Created new verification code with ID {otp.id} for phone {phone_number}")

            text = f"Profigram\nКод подтверждения: {code}. Никому не сообщайте его."
            if not send_sms(phone=phone_number, text=text, transaction_id=otp.id):
                return Response(
                    {"error": "Не удалось отправить SMS"},
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR
                )

            return Response(
                {"message": "Код подтверждения отправлен"},
                status=status.HTTP_201_CREATED
            )

        except Exception as e:
            logger.error(f"Unexpected error while sending SMS to {phone_number}: {str(e)}", exc_info=True)
            return Response(
                {"error": "Внутренняя ошибка сервера"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


@extend_schema(tags=['Auth'])
class VerifyOTPView(APIView):
    serializer_class = serializers.VerifyOTPSerializer

    def post(self, request):
        serializer = self.serializer_class(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=400)

        phone_number = serializer.validated_data.get("phone_number")
        code = serializer.validated_data.get("code")

        try:
            with transaction.atomic():
                obj = OTP.objects.select_for_update().get(
                    phone_number=phone_number,
                    code=code,
                    is_verified=False
                )

                if obj.is_expired():
                    return Response({"error": "Код просрочен"}, status=400)

                obj.is_verified = True
                obj.save()
                logger.info(f"SMS code verified successfully for phone {phone_number}, verification ID {obj.id}")

                user, created = User.objects.get_or_create(phone_number=phone_number)

        except OTP.DoesNotExist:
            return Response({"error": "Неверный код"}, status=400)

        refresh = RefreshToken.for_user(user)
        return Response({
            "refresh": str(refresh),
            "access": str(refresh.access_token),
        })

#
# @extend_schema(tags=['Auth'])
# class PasswordResetRequestView(APIView):
#     serializer_class = serializers.PhoneNumberSerializer
#
#     def post(self, request):
#         serializer = self.serializer_class(data=request.data)
#         if serializer.is_valid():
#             phone_number = serializer.validated_data['phone_number']
#
#             try:
#                 user = User.objects.get(phone_number=phone_number)
#             except User.DoesNotExist:
#                 return Response({"error": "Пользователь не найден"}, status=404)
#
#             code = str(random.randint(1000, 9999))
#             OTP.objects.create(phone_number=phone_number, code=code)
#
#             text = f"Profichat\nКод для сброса пароля: {code}. Никому не сообщайте его."
#             if send_sms(phone=phone_number, text=text):
#                 return Response({"message": "Код отправлен на номер"}, status=200)
#             else:
#                 return Response({"error": "Не удалось отправить SMS"}, status=500)
#
#         return Response(serializer.errors, status=400)
#
#
# @extend_schema(tags=['Auth'])
# class PasswordResetVerifyView(APIView):
#     serializer_class = serializers.VerifyOTPSerializer
#
#     def post(self, request):
#         serializer = self.serializer_class(data=request.data)
#         if serializer.is_valid():
#             phone_number = serializer.validated_data['phone_number']
#             code = serializer.validated_data['code']
#
#             try:
#                 otp = OTP.objects.filter(phone_number=phone_number, code=code, is_verified=False).latest('created_at')
#
#                 if otp.is_expired():
#                     return Response({"error": "Код истёк"}, status=400)
#
#                 otp.is_verified = True
#                 otp.save()
#
#                 return Response({"message": "Код подтверждён"}, status=200)
#             except OTP.DoesNotExist:
#                 return Response({"error": "Неверный код"}, status=400)
#
#         return Response(serializer.errors, status=400)
#
#
# @extend_schema(tags=['Auth'])
# class PasswordResetConfirmView(APIView):
#     serializer_class = serializers.PasswordResetConfirmSerializer  # phone_number, code, new_password
#
#     def post(self, request):
#         serializer = self.serializer_class(data=request.data)
#         if serializer.is_valid():
#             phone_number = serializer.validated_data['phone_number']
#             code = serializer.validated_data['code']
#             new_password = serializer.validated_data['new_password']
#
#             try:
#                 otp = OTP.objects.filter(phone_number=phone_number, code=code, is_verified=True).latest('created_at')
#                 user = User.objects.get(phone_number=phone_number)
#
#                 user.set_password(new_password)
#                 user.save()
#
#                 return Response({"message": "Пароль успешно сброшен"}, status=200)
#             except OTP.DoesNotExist:
#                 return Response({"error": "Код не подтверждён"}, status=400)
#             except User.DoesNotExist:
#                 return Response({"error": "Пользователь не найден"}, status=404)
#
#         return Response(serializer.errors, status=400)
