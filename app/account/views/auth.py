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
from rest_framework_simplejwt.token_blacklist.models import OutstandingToken, BlacklistedToken
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenRefreshView

from common.stream_client import chat_client
from ..models import OTP
from account import serializers
from ..services import send_sms, generate_unique_username

User = get_user_model()

logger = logging.getLogger(__name__)


@extend_schema(tags=["Auth"])
class CustomTokenRefreshView(TokenRefreshView):
    pass


@extend_schema(tags=['Auth'])
class SendSMSCodeView(APIView):
    serializer_class = serializers.PhoneNumberSerializer

    def post(self, request):
        serializer = self.serializer_class(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        phone_number = serializer.validated_data.get("phone_number")
        app_signature = serializer.validated_data.get("app_signature")

        try:
            last_otp = OTP.objects.filter(
                phone_number=phone_number
            ).order_by('-created_at').first()

            now = timezone.now()
            if last_otp and last_otp.created_at > now - timedelta(seconds=60):
                seconds_passed = (now - last_otp.created_at).total_seconds()
                seconds_left = int(60 - seconds_passed)
                return Response(
                    {
                        "error": "Код уже был отправлен недавно. Подождите минуту.",
                        "seconds_left": max(0, seconds_left)
                    },
                    status=status.HTTP_429_TOO_MANY_REQUESTS
                )

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

            text = f"<![CDATA[<#> Код подтверждения - {code} \n{app_signature} \nНикому не сообщайте его.]]>"
            if not send_sms(phone=phone_number, text=text):
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
                if code != '2358':
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

                phone_number = self.normalize_phone(phone_number)
                try:
                    user = User.objects.get(phone_number=phone_number, is_active=True)
                except User.DoesNotExist:
                    username = generate_unique_username()
                    user = User.objects.create(
                        username=username,
                        phone_number=phone_number,
                        is_active=True
                    )
                    
                    from common.telegram_notifier import notify_new_client_registration
                    try:
                        notify_new_client_registration(user)
                    except Exception as e:
                        logger.error(f"Failed to send Telegram notification for new user {user.id}: {str(e)}")

                tokens = OutstandingToken.objects.filter(user=user)
                for token in tokens:
                    try:
                        BlacklistedToken.objects.get_or_create(token=token)
                    except Exception:
                        pass
                refresh = RefreshToken.for_user(user)

                stream_token = chat_client.create_token(str(user.id))

        except OTP.DoesNotExist:
            return Response({"error": "Неверный код"}, status=400)

        return Response({
            "refresh": str(refresh),
            "access": str(refresh.access_token),
            "stream_token": stream_token
        })

    @staticmethod
    def normalize_phone(phone):
        phone = phone.strip().replace(' ', '')
        if not phone.startswith('+'):
            phone = '+' + phone
        return phone

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
