from django.contrib import admin

from common.admin import BaseModelAdmin
from ..models import Organization


@admin.register(Organization)
class OrganizationAdmin(BaseModelAdmin):
    list_display = ("id", "name", "is_active", "created_at", "detail_link")
    list_display_links = ("id", "name")
    search_fields = ("name",)
    list_filter = ("is_active", "created_at")
