from django.contrib import admin

from messenger.models import Call, Message


@admin.register(Message)
class MessageAdmin(admin.ModelAdmin):
    list_display = ("id", "chat", "sender", "type", "custom_type", "created_at", "deleted_at")
    list_filter = ("type",)
    search_fields = ("text", "chat__channel_id")
    raw_id_fields = ("chat", "sender", "reply_to", "call")
    ordering = ("-created_at", "-id")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Call)
class CallAdmin(admin.ModelAdmin):
    list_display = ("id", "chat", "caller", "callee", "kind", "status", "created_at", "duration_seconds")
    list_filter = ("status", "kind")
    raw_id_fields = ("chat", "caller", "callee")
    search_fields = ("room_name", "chat__channel_id")
