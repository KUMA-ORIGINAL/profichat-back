from django.contrib import admin
from common.admin import BaseModelAdmin
from ..models import Chat


@admin.register(Chat)
class ChatAdmin(BaseModelAdmin):
    list_display = (
        'id',
        'client',
        'specialist',
        'channel_id',
        'created_at',
        'detail_link'
    )
    list_filter = ('created_at',)
    search_fields = (
        'client__username',
        'client__email',
        'specialist__username',
        'specialist__email',
        'channel_id',
    )
    autocomplete_fields = ('client', 'specialist')
