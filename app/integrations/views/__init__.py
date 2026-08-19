from .medcrm import MedCRMInviteClientView, MedCRMTariffsView
from .telegram_auth import (
    TelegramAuthStartView,
    TelegramAuthStatusView,
    TelegramAuthWebhookView,
)
from .telegram_admin import TelegramAdminWebhookView
from .sso import SecondSystemWebviewUrlView, VerifySecondSystemSSOTokenView
from .mamadoc import (
    MamadocAppointmentsView,
    MamadocConclusionView,
    MamadocBookingView,
    MamadocBookingCancelView,
    MamadocProfessionalsView,
    MamadocServicesView,
    MamadocOrganizationView,
    MamadocBranchesView,
)

__all__ = [
    "MedCRMInviteClientView",
    "MedCRMTariffsView",
    "SecondSystemWebviewUrlView",
    "TelegramAuthStartView",
    "TelegramAuthStatusView",
    "TelegramAuthWebhookView",
    "TelegramAdminWebhookView",
    "VerifySecondSystemSSOTokenView",
    "MamadocAppointmentsView",
    "MamadocConclusionView",
    "MamadocBookingView",
    "MamadocBookingCancelView",
    "MamadocProfessionalsView",
    "MamadocServicesView",
    "MamadocOrganizationView",
    "MamadocBranchesView",
]
