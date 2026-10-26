from django.urls import path

from messenger.views import attachments, messages, realtime, system_messages

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
    path("chats/<str:channel_id>/read/", messages.ChatReadView.as_view(), name="messenger-chat-read"),
    path(
        "chats/<str:channel_id>/system-messages/",
        system_messages.ChatSystemMessageView.as_view(),
        name="messenger-system-messages",
    ),
]
