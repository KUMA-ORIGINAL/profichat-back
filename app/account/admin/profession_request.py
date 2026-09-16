from django.contrib import admin, messages
from django.utils import timezone

from common.admin import BaseModelAdmin
from ..models import ProfessionRequest
from ..services.profession_request import (
    ProfessionRequestAlreadyReviewed,
    apply_approval_effects,
    apply_rejection_effects,
    approve_profession_request,
)


@admin.register(ProfessionRequest)
class ProfessionRequestAdmin(BaseModelAdmin):
    list_display = ("id", "name", "user", "source", "status", "profession_category", "created_at", "detail_link")
    list_display_links = ("id", "name")
    list_filter = ("status", "source", "created_at")
    search_fields = ("name", "description", "user__first_name", "user__last_name", "user__phone_number")
    autocomplete_fields = ("user", "profession_category")
    raw_id_fields = ("application",)
    readonly_fields = ("source", "application", "reviewed_at", "created_at", "updated_at")
    date_hierarchy = "created_at"
    ordering = ("-created_at",)
    actions = ("approve_selected",)
    fieldsets = (
        (None, {"fields": ("user", "name", "description", "source", "application")}),
        ("Решение", {
            "fields": ("status", "profession_category", "reason", "reviewed_at"),
            "description": (
                "Одобрение: если категория не выбрана, она будет создана по названию заявки. "
                "Заявителю из анкеты профессия проставится в анкету (и в профиль, если анкета уже принята), "
                "специалисту из профиля — сразу в профиль."
            ),
        }),
        ("Служебное", {"fields": ("created_at", "updated_at"), "classes": ("collapse",)}),
    )

    def save_model(self, request, obj, form, change):
        old_status = None
        if change and obj.pk:
            old_status = type(obj).objects.filter(pk=obj.pk).values_list('status', flat=True).first()

        status_changed = old_status is not None and old_status != obj.status
        if status_changed:
            obj.reviewed_at = timezone.now()
            if obj.status == ProfessionRequest.STATUS_APPROVED:
                obj.reason = ''

        super().save_model(request, obj, form, change)

        if not status_changed:
            return

        if old_status != ProfessionRequest.STATUS_PENDING:
            self.message_user(
                request,
                f"Заявка уже была рассмотрена ранее (статус: {old_status}), решение изменено.",
                level=messages.WARNING,
            )

        reviewer = getattr(request.user, 'username', '') or 'admin'
        if obj.status == ProfessionRequest.STATUS_APPROVED:
            apply_approval_effects(obj, reviewed_by=reviewer)
            self.message_user(
                request,
                f"Профессия «{obj.profession_category.name}» добавлена в справочник.",
                level=messages.SUCCESS,
            )
        elif obj.status == ProfessionRequest.STATUS_REJECTED:
            apply_rejection_effects(obj, reviewed_by=reviewer)

    @admin.action(description="Одобрить выбранные заявки (создать категории)")
    def approve_selected(self, request, queryset):
        reviewer = getattr(request.user, 'username', '') or 'admin'
        approved = skipped = 0
        for item in queryset:
            try:
                approve_profession_request(item, reviewed_by=reviewer)
                approved += 1
            except ProfessionRequestAlreadyReviewed:
                skipped += 1
        if approved:
            self.message_user(request, f"Одобрено заявок: {approved}.", level=messages.SUCCESS)
        if skipped:
            self.message_user(request, f"Пропущено уже рассмотренных: {skipped}.", level=messages.WARNING)
