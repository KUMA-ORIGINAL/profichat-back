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

__all__ = [
    "MedCRMInviteClientSerializer",
    "MedCRMInviteResponseSerializer",
    "MedCRMTariffSerializer",
    "TelegramAuthErrorResponseSerializer",
    "TelegramAuthStartResponseSerializer",
    "TelegramAuthStatusRequestSerializer",
    "TelegramAuthStatusResponseSerializer",
]
