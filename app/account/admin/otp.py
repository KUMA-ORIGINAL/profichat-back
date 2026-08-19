from django.contrib import admin
from django.utils.translation import gettext_lazy as _

from account.models import OTP
from common.admin import BaseModelAdmin


@admin.register(OTP)
class OTPAdmin(BaseModelAdmin):
    list_display = (
        "id",
        "phone_number",
        "code",
        "channel",
        "is_verified",
        "is_alive",
        "created_at",
        "sms_resent_at",
    )
    list_filter = ("channel", "is_verified", "created_at")
    search_fields = ("phone_number", "code")
    readonly_fields = ("created_at", "sms_resent_at")
    ordering = ("-created_at",)

    @admin.display(description=_("Код ещё действителен"), boolean=True)
    def is_alive(self, obj):
        return not obj.is_expired()

    def has_add_permission(self, request):
        return False
