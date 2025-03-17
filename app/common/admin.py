from django.contrib import admin
from django.urls import reverse
from django.utils.safestring import mark_safe
from django.utils.translation import gettext_lazy as _

from unfold.admin import ModelAdmin as UnfoldModelAdmin


class BaseModelAdmin(UnfoldModelAdmin):

    @admin.display(description=_("Подробнее"))
    def detail_link(self, obj):
        if obj and obj.id:
            url = reverse('admin:%s_%s_change' % (obj._meta.app_label, obj._meta.model_name),
                          args=[obj.id])
            return mark_safe(
                '<a class="button" href="{}">{}</a>'.format(url, _("Подробнее"))
            )
        return "-"
