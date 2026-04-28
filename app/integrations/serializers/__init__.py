from .medcrm import (
    MedCRMInviteClientSerializer,
    MedCRMInviteResponseSerializer,
    MedCRMTariffSerializer,
)
from .telegram_auth import (
    TelegramAuthErrorResponseSerializer,
    TelegramAuthStartResponseSerializer,
    TelegramAuthStatusRequestSerializer,
    TelegramAuthStatusResponseSerializer,
)
from .sso import (
    SecondSystemWebviewUrlRequestSerializer,
    SecondSystemWebviewUrlResponseSerializer,
    VerifySecondSystemSSOTokenRequestSerializer,
    VerifySecondSystemSSOTokenResponseSerializer,
)

__all__ = [
    "MedCRMInviteClientSerializer",
    "MedCRMInviteResponseSerializer",
    "MedCRMTariffSerializer",
    "TelegramAuthErrorResponseSerializer",
    "TelegramAuthStartResponseSerializer",
    "TelegramAuthStatusRequestSerializer",
    "TelegramAuthStatusResponseSerializer",
    "SecondSystemWebviewUrlRequestSerializer",
    "SecondSystemWebviewUrlResponseSerializer",
    "VerifySecondSystemSSOTokenRequestSerializer",
    "VerifySecondSystemSSOTokenResponseSerializer",
]
