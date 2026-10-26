from django.urls import path

from messenger.views import realtime

urlpatterns = [
    path("messenger/connection-token/", realtime.ConnectionTokenView.as_view(), name="messenger-connection-token"),
    path(
        "chats/<str:channel_id>/subscription-token/",
        realtime.SubscriptionTokenView.as_view(),
        name="messenger-subscription-token",
    ),
]
