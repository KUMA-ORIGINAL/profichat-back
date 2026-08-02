from django.urls import path

from .views import (
    MedCRMInviteClientView,
    MedCRMTariffsView,
    SecondSystemWebviewUrlView,
    TelegramAuthStartView,
    TelegramAuthStatusView,
    TelegramAuthWebhookView,
    VerifySecondSystemSSOTokenView,
    MamadocAppointmentsView,
    MamadocConclusionView,
    MamadocBookingView,
)

app_name = "integrations"

urlpatterns = [
    path(
        "telegram/auth/start/",
        TelegramAuthStartView.as_view(),
        name="telegram-auth-start",
    ),
    path(
        "telegram/auth/status/",
        TelegramAuthStatusView.as_view(),
        name="telegram-auth-status",
    ),
    path(
        "telegram/auth/webhook/",
        TelegramAuthWebhookView.as_view(),
        name="telegram-auth-webhook",
    ),
    path(
        "telegram/auth/webhook/<str:webhook_secret>/",
        TelegramAuthWebhookView.as_view(),
        name="telegram-auth-webhook-secret",
    ),
    path(
        "medcrm/tariffs/",
        MedCRMTariffsView.as_view(),
        name="medcrm-tariffs",
    ),
    path(
        "medcrm/invite-client/",
        MedCRMInviteClientView.as_view(),
        name="medcrm-invite-client",
    ),
    path(
        "medcrm/webview-url/",
        SecondSystemWebviewUrlView.as_view(),
        name="medcrm-sso-webview-url",
    ),
    path(
        "medcrm/verify-sso-token/",
        VerifySecondSystemSSOTokenView.as_view(),
        name="medcrm-sso-verify-token",
    ),
    path(
        "newcrm/appointments/",
        MamadocAppointmentsView.as_view(),
        name="newcrm-appointments",
    ),
    path(
        "newcrm/conclusions/<int:conclusion_id>/",
        MamadocConclusionView.as_view(),
        name="newcrm-conclusion-detail",
    ),
    path(
        "newcrm/booking/appointments/",
        MamadocBookingView.as_view(),
        name="newcrm-booking-appointments",
    ),
]
