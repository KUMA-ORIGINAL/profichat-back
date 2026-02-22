from django.urls import path

from . import views

app_name = "integrations"

urlpatterns = [
    path(
        "medcrm/tariffs/",
        views.MedCRMTariffsView.as_view(),
        name="medcrm-tariffs",
    ),
    path(
        "medcrm/invite-client/",
        views.MedCRMInviteClientView.as_view(),
        name="medcrm-invite-client",
    ),
]
