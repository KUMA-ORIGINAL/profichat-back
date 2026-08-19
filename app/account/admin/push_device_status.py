from django.contrib import admin
from django.db import models
from django.utils.translation import gettext_lazy as _

from account.models import PushDeviceStatus
from common.admin import BaseModelAdmin


class DeliveryStateFilter(admin.SimpleListFilter):
    """Фильтр «в каком состоянии доставка», без разбора кодов ошибок вручную."""

    title = _("Состояние доставки")
    parameter_name = "delivery_state"

    def lookups(self, request, model_admin):
        return (
            ("ok", _("Последняя отправка успешна")),
            ("failing", _("Последняя отправка провалилась")),
            ("dead", _("Токен признан нерабочим")),
        )

    def queryset(self, request, queryset):
        value = self.value()
        if value == "dead":
            return queryset.filter(deactivated_at__isnull=False)
        if value == "failing":
            return queryset.filter(last_failure_at__isnull=False).exclude(
                last_success_at__gte=models.F("last_failure_at")
            )
        if value == "ok":
            return queryset.filter(last_success_at__isnull=False).filter(
                models.Q(last_failure_at__isnull=True)
                | models.Q(last_success_at__gte=models.F("last_failure_at"))
            )
        return queryset


@admin.register(PushDeviceStatus)
class PushDeviceStatusAdmin(BaseModelAdmin):
    list_display = (
        "id",
        "user",
        "device",
        "is_device_active",
        "last_success_at",
        "last_failure_at",
        "last_error_code",
        "deactivated_at",
    )
    list_filter = (DeliveryStateFilter, "last_error_code", "device__active", "last_failure_at")
    search_fields = (
        "device__registration_id",
        "device__user__phone_number",
        "device__user__username",
        "last_error_code",
        "last_error_message",
    )
    raw_id_fields = ("device",)
    readonly_fields = (
        "device",
        "last_success_at",
        "last_failure_at",
        "last_error_code",
        "last_error_message",
        "deactivated_at",
        "created_at",
        "updated_at",
    )
    ordering = ("-updated_at",)

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("device", "device__user")

    @admin.display(description=_("Пользователь"), ordering="device__user")
    def user(self, obj):
        return obj.device.user

    @admin.display(description=_("Устройство активно"), boolean=True, ordering="device__active")
    def is_device_active(self, obj):
        return obj.device.active

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
