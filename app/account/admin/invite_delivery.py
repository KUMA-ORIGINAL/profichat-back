from django.contrib import admin

from common.admin import BaseModelAdmin
from account.models import InviteDelivery


@admin.register(InviteDelivery)
class InviteDeliveryAdmin(BaseModelAdmin):
    list_display = (
        "id",
        "created_at",
        "specialist",
        "client",
        "chat",
        "channel",
        "status",
        "provider_status",
    )
    list_filter = ("channel", "status", "is_new_client", "created_at")
    search_fields = (
        "specialist__phone_number",
        "client__phone_number",
        "chat__channel_id",
        "provider_message_id",
        "error_message",
    )
    autocomplete_fields = ("specialist", "client", "chat")
    readonly_fields = (
        "created_at",
        "updated_at",
    )
