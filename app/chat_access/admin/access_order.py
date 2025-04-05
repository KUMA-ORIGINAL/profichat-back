from django.contrib import admin

from common.admin import BaseModelAdmin
from ..models import AccessOrder


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
    )
    list_filter = ('payment_status', 'tariff__tariff_type', 'specialist')
    search_fields = ('client__username', 'specialist__username')
    autocomplete_fields = ('client', 'specialist', 'tariff')
    readonly_fields = ('created_at', 'activated_at', 'expires_at')

