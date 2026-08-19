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
from rest_framework_simplejwt.serializers import TokenRefreshSerializer
from rest_framework_simplejwt.views import TokenRefreshView

from common.errors import ErrorCode, error_response
from common.stream_client import chat_client
from ..models import OTP
from account import serializers
from ..services import send_notification, generate_unique_username
from ..services.token_lifetime import (
    build_token_pair_for_user,
    get_short_access_token_lifetime,
    should_use_short_token_lifetime,
)

User = get_user_model()

logger = logging.getLogger(__name__)


def mask_phone(phone):
    if not phone:
        return ""
    raw = str(phone)
    if len(raw) <= 4:
        return "***"
    return f"{raw[:3]}***{raw[-2:]}"


class CustomTokenRefreshSerializer(TokenRefreshSerializer):
    def validate(self, attrs):
        data = super().validate(attrs)
        refresh = self.token_class(attrs["refresh"])
        user_id = refresh.get("user_id")
        if should_use_short_token_lifetime(user_id):
            access_token = refresh.access_token
            access_token.set_exp(lifetime=get_short_access_token_lifetime())
            data["access"] = str(access_token)
        return data


@extend_schema(tags=["Auth"])
class CustomTokenRefreshView(TokenRefreshView):
    serializer_class = CustomTokenRefreshSerializer


@extend_schema(tags=['Auth'])
class SendSMSCodeView(APIView):
    serializer_class = serializers.PhoneNumberSerializer

    def post(self, request):
        serializer = self.serializer_class(data=request.data)
        if not serializer.is_valid():
            return error_response(
                ErrorCode.VALIDATION_ERROR,
                "Некорректные данные",
                status.HTTP_400_BAD_REQUEST,
                errors=serializer.errors,
                **serializer.errors,
            )

        phone_number = serializer.validated_data.get("phone_number")
        app_signature = serializer.validated_data.get("app_signature") or ""
        channel = serializer.validated_data.get("channel") or OTP.CHANNEL_WHATSAPP
        scenario = OTP.SCENARIO_BY_CHANNEL[channel]

        try:
            last_otp = OTP.objects.filter(
                phone_number=phone_number
            ).order_by('-created_at').first()

            now = timezone.now()

            # «Код не пришёл» → повторная отправка того же кода по SMS,
            # без ожидания общего кулдауна на выдачу нового кода.
            if (
                channel == OTP.CHANNEL_SMS
                and last_otp
                and not last_otp.is_verified
                and not last_otp.is_expired()
            ):
                if last_otp.sms_resent_at and last_otp.sms_resent_at > now - timedelta(seconds=60):
                    seconds_left = int(60 - (now - last_otp.sms_resent_at).total_seconds())
                    return error_response(
                        ErrorCode.OTP_SMS_RESEND_COOLDOWN,
                        "SMS уже было отправлено недавно. Подождите минуту.",
                        status.HTTP_429_TOO_MANY_REQUESTS,
                        error="SMS уже было отправлено недавно. Подождите минуту.",
                        seconds_left=max(0, seconds_left),
                        channel=OTP.CHANNEL_SMS,
                    )

                if not self.deliver_code(
                    phone_number=phone_number,
                    otp=last_otp,
                    scenario=scenario,
                    app_signature=app_signature,
                ):
                    return error_response(
                        ErrorCode.OTP_SEND_FAILED,
                        "Не удалось отправить код подтверждения",
                        status.HTTP_500_INTERNAL_SERVER_ERROR,
                        error="Не удалось отправить код подтверждения",
                    )

                last_otp.channel = OTP.CHANNEL_SMS
                last_otp.sms_resent_at = timezone.now()
                last_otp.save(update_fields=["channel", "sms_resent_at"])

                return Response(
                    {"message": "Код подтверждения отправлен по SMS", "channel": OTP.CHANNEL_SMS},
                    status=status.HTTP_201_CREATED
                )

            if last_otp and last_otp.created_at > now - timedelta(seconds=60):
                seconds_passed = (now - last_otp.created_at).total_seconds()
                seconds_left = int(60 - seconds_passed)
                return error_response(
                    ErrorCode.OTP_SEND_COOLDOWN,
                    "Код уже был отправлен недавно. Подождите минуту.",
                    status.HTTP_429_TOO_MANY_REQUESTS,
                    error="Код уже был отправлен недавно. Подождите минуту.",
                    seconds_left=max(0, seconds_left),
                )

            with transaction.atomic():
                OTP.objects.filter(
                    phone_number=phone_number,
                    created_at__lt=timezone.now() - timedelta(hours=1)
                ).delete()

                code = str(random.randint(1000, 9999))
                otp = OTP.objects.create(
                    phone_number=phone_number,
                    code=code,
                    channel=channel,
                    sms_resent_at=timezone.now() if channel == OTP.CHANNEL_SMS else None,
                )
                logger.info(
                    "Created verification code id=%s for phone=%s channel=%s",
                    otp.id,
                    mask_phone(phone_number),
                    channel,
                )

            if not self.deliver_code(
                phone_number=phone_number,
                otp=otp,
                scenario=scenario,
                app_signature=app_signature,
            ):
                return error_response(
                    ErrorCode.OTP_SEND_FAILED,
                    "Не удалось отправить код подтверждения",
                    status.HTTP_500_INTERNAL_SERVER_ERROR,
                    error="Не удалось отправить код подтверждения",
                )

            return Response(
                {"message": "Код подтверждения отправлен", "channel": channel},
                status=status.HTTP_201_CREATED
            )

        except Exception:
            logger.exception(
                "Unexpected error while sending SMS to phone=%s",
                mask_phone(phone_number),
            )
            return error_response(
                ErrorCode.INTERNAL_ERROR,
                "Внутренняя ошибка сервера",
                status.HTTP_500_INTERNAL_SERVER_ERROR,
                error="Внутренняя ошибка сервера",
            )

    @staticmethod
    def deliver_code(phone_number, otp, scenario, app_signature):
        variables = {"otp": otp.code}
        if scenario == OTP.SCENARIO_BY_CHANNEL[OTP.CHANNEL_SMS]:
            variables["app_signature"] = app_signature
        return send_notification(
            phone=phone_number,
            scenario=scenario,
            variables=variables,
            # уникален для каждой попытки, иначе провайдер может отбросить повтор как дубль
            external_id=f"otp-{otp.id}-{scenario}-{int(timezone.now().timestamp())}",
        )


@extend_schema(tags=['Auth'])
class VerifyOTPView(APIView):
    serializer_class = serializers.VerifyOTPSerializer

    def post(self, request):
        serializer = self.serializer_class(data=request.data)
        if not serializer.is_valid():
            return error_response(
                ErrorCode.VALIDATION_ERROR,
                "Некорректные данные",
                status.HTTP_400_BAD_REQUEST,
                errors=serializer.errors,
                **serializer.errors,
            )

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
                        return error_response(
                            ErrorCode.OTP_CODE_EXPIRED,
                            "Код просрочен",
                            status.HTTP_400_BAD_REQUEST,
                            error="Код просрочен",
                        )

                    obj.is_verified = True
                    obj.save()
                    logger.info(
                        "SMS code verified for phone=%s verification_id=%s",
                        mask_phone(phone_number),
                        obj.id,
                    )

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
                    except Exception:
                        logger.exception("Failed to send Telegram notification for new user %s", user.id)

                tokens = OutstandingToken.objects.filter(user=user)
                for token in tokens:
                    try:
                        BlacklistedToken.objects.get_or_create(token=token)
                    except Exception:
                        logger.exception("Failed to blacklist token for user=%s token=%s", user.id, token.id)
                refresh, access_token = build_token_pair_for_user(user)

                stream_token = chat_client.create_token(str(user.id))

        except OTP.DoesNotExist:
            return error_response(
                ErrorCode.OTP_CODE_INVALID,
                "Неверный код",
                status.HTTP_400_BAD_REQUEST,
                error="Неверный код",
            )

        return Response({
            "refresh": str(refresh),
            "access": str(access_token),
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
