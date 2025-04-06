from django.contrib import admin

from payouts.models import PayoutMethod
from common.admin import BaseModelAdmin


@admin.register(PayoutMethod)
class PayoutMethodAdmin(BaseModelAdmin):
    list_display = ('id', 'name', 'is_active')
    list_editable = ('is_active',)
    search_fields = ('name',)
    ordering = ('id',)
