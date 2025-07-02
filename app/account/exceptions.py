from rest_framework.views import exception_handler
from rest_framework_simplejwt.exceptions import TokenError, InvalidToken, AuthenticationFailed
from rest_framework import status
from rest_framework.response import Response


def custom_exception_handler(exc, context):
    # Перехватываем ошибки SimpleJWT и DRF
    if isinstance(exc, (InvalidToken, TokenError, AuthenticationFailed)):
        reason = 'unknown'
        message = 'Ошибка авторизации'

        # Получаем detail и code
        detail = getattr(exc, 'detail', None)
        code = getattr(exc, 'code', '')

        # Обработка разных detail
        if detail:
            detail_str = str(detail)
            if 'blacklisted' in detail_str.lower():
                reason = 'logged_in_from_another_device'
                message = 'Вы вошли с другого устройства'
            elif 'expired' in detail_str.lower():
                reason = 'token_expired'
                message = 'Срок действия токена истёк'
            elif 'invalid' in detail_str.lower():
                reason = 'invalid_token'
                message = 'Некорректный токен'

        response_data = {
            "error": "Unauthorized",
            "reason": reason,
            "message": message
        }
        return Response(response_data, status=status.HTTP_401_UNAUTHORIZED)

    # Для других ошибок — стандартный обработчик
    return exception_handler(exc, context)