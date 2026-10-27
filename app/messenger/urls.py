from django.urls import path

from messenger.views import attachments, calls, livekit_webhook, messages, realtime, system_messages, voip_devices

urlpatterns = [
    path("messenger/connection-token/", realtime.ConnectionTokenView.as_view(), name="messenger-connection-token"),
    path(
        "chats/<str:channel_id>/subscription-token/",
        realtime.SubscriptionTokenView.as_view(),
        name="messenger-subscription-token",
    ),
    path("chats/<str:channel_id>/messages/", messages.ChatMessagesView.as_view(), name="messenger-messages"),
    path(
        "chats/<str:channel_id>/messages/<int:pk>/",
        messages.ChatMessageDetailView.as_view(),
        name="messenger-message-detail",
    ),
    path(
        "chats/<str:channel_id>/attachments/",
        attachments.ChatAttachmentUploadView.as_view(),
        name="messenger-attachment-upload",
    ),
    path("messages/search/", messages.MessageSearchView.as_view(), name="messenger-message-search"),
    path("chats/<str:channel_id>/read/", messages.ChatReadView.as_view(), name="messenger-chat-read"),
    path("chats/<str:channel_id>/unread/", messages.ChatUnreadView.as_view(), name="messenger-chat-unread"),
    path(
        "chats/<str:channel_id>/system-messages/",
        system_messages.ChatSystemMessageView.as_view(),
        name="messenger-system-messages",
    ),
    path("chats/<str:channel_id>/calls/", calls.ChatCallsView.as_view(), name="messenger-chat-calls"),
    path("calls/active/", calls.ActiveCallView.as_view(), name="messenger-call-active"),
    path("calls/<uuid:pk>/", calls.CallDetailView.as_view(), name="messenger-call-detail"),
    path("calls/<uuid:pk>/accept/", calls.AcceptCallView.as_view(), name="messenger-call-accept"),
    path("calls/<uuid:pk>/decline/", calls.DeclineCallView.as_view(), name="messenger-call-decline"),
    path("calls/<uuid:pk>/cancel/", calls.CancelCallView.as_view(), name="messenger-call-cancel"),
    path("calls/<uuid:pk>/end/", calls.EndCallView.as_view(), name="messenger-call-end"),
    path(
        "messenger/livekit-webhook/",
        livekit_webhook.LiveKitWebhookView.as_view(),
        name="messenger-livekit-webhook",
    ),
    path("messenger/voip-devices/", voip_devices.VoipDevicesView.as_view(), name="messenger-voip-devices"),
    path(
        "messenger/voip-devices/<str:token>/",
        voip_devices.VoipDeviceDetailView.as_view(),
        name="messenger-voip-device-detail",
    ),
]
