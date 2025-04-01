from django.contrib import admin
from unfold.admin import TabularInline

from common.admin import BaseModelAdmin
from ..models import Application, WorkExperience, ROLE_SPECIALIST


class WorkExperienceInline(TabularInline):
    model = WorkExperience
    extra = 1


@admin.register(Application)
class ApplicationAdmin(BaseModelAdmin):
    list_display = ("id", "first_name", "last_name", 'profession', 'status', "created_at", 'detail_link')
    list_display_links = ("id", "first_name")
    search_fields = ("first_name", "last_name", "profession", "education")
    list_filter = ("profession", "created_at", 'status')
    date_hierarchy = "created_at"
    ordering = ("-created_at",)
    inlines = [WorkExperienceInline]

    def save_model(self, request, obj, form, change):
        if change:
            if obj.status == 'accepted':
                obj.rejection_reason = ''
                user = obj.user
                user.role = ROLE_SPECIALIST
                user.save()
        super().save_model(request, obj, form, change)
