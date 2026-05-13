from django.contrib import admin
from django.utils.safestring import mark_safe

from common.admin import BaseModelAdmin
from ..models import Organization


@admin.register(Organization)
class OrganizationAdmin(BaseModelAdmin):
    list_display = ("id", "name", "display_logo", "rating", "is_active", "created_at", "detail_link")
    list_display_links = ("id", "name")
    search_fields = ("name", "description")
    list_filter = ("is_active", "created_at")

    def display_logo(self, obj):
        if obj.logo:
            return mark_safe(f'<img src="{obj.logo.url}" width="50" height="50" />')
        return "-"

    display_logo.short_description = "Логотип"
