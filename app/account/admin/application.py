from django.contrib import admin, messages
from unfold.admin import TabularInline

from common.admin import BaseModelAdmin
from ..models import Application, WorkExperience
from ..services.application_review import (
    STATUS_ACCEPTED,
    STATUS_PENDING,
    STATUS_REJECTED,
    apply_approval_effects,
    apply_rejection_effects,
)


class WorkExperienceInline(TabularInline):
    model = WorkExperience
    extra = 1


@admin.register(Application)
class ApplicationAdmin(BaseModelAdmin):
    list_display = ("id", "first_name", "last_name", 'profession', 'custom_profession', 'organization', 'custom_organization', 'status', "created_at", 'detail_link')
    list_display_links = ("id", "first_name")
    search_fields = ("first_name", "last_name", "profession__name", "custom_profession", "organization__name", "custom_organization", "education")
    list_filter = ("profession", "organization", "created_at", 'status')
    date_hierarchy = "created_at"
    ordering = ("-created_at",)
    inlines = [WorkExperienceInline]

    def save_model(self, request, obj, form, change):
        old_status = None
        if change and obj.pk:
            old_status = type(obj).objects.filter(pk=obj.pk).values_list('status', flat=True).first()

        status_changed = old_status is not None and old_status != obj.status
        if status_changed and obj.status == STATUS_ACCEPTED:
            obj.rejection_reason = ''

        super().save_model(request, obj, form, change)

        if not status_changed:
            return

        # Заявку могли уже рассмотреть кнопкой в Telegram — предупреждаем,
        # но применяем решение админки, оно приоритетнее.
        if old_status != STATUS_PENDING:
            self.message_user(
                request,
                f"Заявка уже была рассмотрена ранее (статус: {old_status}), решение изменено.",
                level=messages.WARNING,
            )

        reviewer = getattr(request.user, 'username', '') or 'admin'
        if obj.status == STATUS_ACCEPTED:
            apply_approval_effects(obj, reviewed_by=reviewer)
        elif obj.status == STATUS_REJECTED:
            apply_rejection_effects(obj, reviewed_by=reviewer)
