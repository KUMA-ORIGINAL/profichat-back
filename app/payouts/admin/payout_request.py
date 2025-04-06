from django.contrib import admin

from payouts.models import PayoutRequest
from common.admin import BaseModelAdmin


@admin.register(PayoutRequest)
class PayoutRequestAdmin(BaseModelAdmin):
    list_display = (
        'id',
        'user',
        'method',
        'amount',
        'phone_number',
        'status',
        'created_at',
        'processed_at',
    )
    list_filter = ('status', 'method')
    search_fields = ('user__username', 'phone_number')
    autocomplete_fields = ('user', 'method')
    readonly_fields = ('created_at', 'processed_at')
