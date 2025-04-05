from django.contrib import admin

from common.admin import BaseModelAdmin
from ..models import Tariff


@admin.register(Tariff)
class TariffAdmin(BaseModelAdmin):
    list_display = (
        'id',
        'specialist',
        'name',
        'duration_hours',
        'tariff_type',
        'price',
        'is_active',
        'detail_link'
    )
    list_filter = ('tariff_type', 'is_active')
    search_fields = ('name', 'specialist__username')
    autocomplete_fields = ('specialist',)
    ordering = ('-id',)
