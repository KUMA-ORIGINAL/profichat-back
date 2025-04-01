from django.contrib import admin
from unfold.admin import TabularInline

from common.admin import BaseModelAdmin
from ..models import Application, WorkExperience


class WorkExperienceInline(TabularInline):
    model = WorkExperience
    extra = 1


@admin.register(Application)
class ApplicationAdmin(BaseModelAdmin):
    list_display = ("id", "first_name", "last_name", "profession", "education", "created_at", 'detail_link')
    list_display_links = ("id", "first_name")
    search_fields = ("first_name", "last_name", "profession", "education")
    list_filter = ("profession", "created_at")
    ordering = ("-created_at",)
    inlines = [WorkExperienceInline]
