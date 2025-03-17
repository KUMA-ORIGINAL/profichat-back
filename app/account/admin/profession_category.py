from django.contrib import admin
from django.utils.safestring import mark_safe

from ..models import ProfessionCategory
from common.admin import BaseModelAdmin


@admin.register(ProfessionCategory)
class ProfessionCategoryAdmin(BaseModelAdmin):
    list_display = ("id", "name", "display_photo")
    search_fields = ("name",)

    def display_photo(self, obj):
        if obj.photo:
            return mark_safe(f'<img src="{obj.photo.url}" width="50" height="50" />')
        return "-"

    display_photo.short_description = "Фото"
