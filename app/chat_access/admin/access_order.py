from django.contrib import admin
from django.utils import timezone
from unfold.contrib.filters.admin import (
    ChoicesDropdownFilter,
    FieldTextFilter,
    RangeDateTimeFilter,
    RangeNumericFilter,
    RelatedDropdownFilter,
)

from common.admin import BaseModelAdmin
from ..models import AccessOrder


class ActiveNowFilter(admin.SimpleListFilter):
    title = "Активен сейчас"
    parameter_name = "is_active_now"

    def lookups(self, request, model_admin):
        return (
            ("yes", "Да"),
            ("no", "Нет"),
        )

    def queryset(self, request, queryset):
        now = timezone.now()
        value = self.value()
        if value == "yes":
            return queryset.filter(payment_status="success", expires_at__gt=now)
        if value == "no":
            return queryset.exclude(payment_status="success", expires_at__gt=now)
        return queryset


@admin.register(AccessOrder)
class AccessOrderAdmin(BaseModelAdmin):
    list_display = (
        'id',
        'client',
        'specialist',
        'tariff__name',
        'payment_status',
        'is_active',
        'tariff_type',
        'price',
        'created_at',
        'activated_at',
        'expires_at',
        'detail_link'
    )
    list_filter = (
        ActiveNowFilter,
        ("payment_status", ChoicesDropdownFilter),
        ("tariff_type", ChoicesDropdownFilter),
        ("specialist", RelatedDropdownFilter),
        ("chat__channel_id", FieldTextFilter),
        ("created_at", RangeDateTimeFilter),
        ("activated_at", RangeDateTimeFilter),
        ("expires_at", RangeDateTimeFilter),
        ("price", RangeNumericFilter),
    )
    search_fields = (
        "=id",
        "=client__id",
        "=specialist__id",  
        "client__username",
        "client__first_name",
        "client__last_name",
        "client__phone_number",
        "specialist__username",
        "specialist__first_name",
        "specialist__last_name",
        "specialist__phone_number",
        "chat__channel_id",
    )
    autocomplete_fields = ('client', 'specialist', 'tariff')
    readonly_fields = ('created_at', 'activated_at', 'expires_at')
    list_select_related = ("client", "specialist", "tariff", "chat")
