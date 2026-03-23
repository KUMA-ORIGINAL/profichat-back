from django.contrib import admin

from account.models import Notification
from common.admin import BaseModelAdmin


@admin.register(Notification)
class NotificationAdmin(BaseModelAdmin):
    list_display = ("id", "recipient", "notification_type", "title", "is_read", "created_at")
    list_filter = ("notification_type", "is_read", "created_at")
    search_fields = ("title", "message", "recipient__username", "recipient__phone_number")
    readonly_fields = ("created_at", "updated_at", "read_at", "pushed_at")
