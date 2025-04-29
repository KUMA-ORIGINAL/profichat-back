from django.contrib import admin
from django.contrib.auth.admin import UserAdmin, GroupAdmin
from django.contrib.auth.models import Group
from django.utils.translation import gettext_lazy as _
from unfold.admin import TabularInline

from unfold.forms import AdminPasswordChangeForm, UserChangeForm, UserCreationForm

from common.admin import BaseModelAdmin
from ..models import User, WorkSchedule

admin.site.unregister(Group)


@admin.register(Group)
class GroupAdmin(GroupAdmin, BaseModelAdmin):
    pass


class WorkScheduleInline(TabularInline):
    model = WorkSchedule
    extra = 0


@admin.register(User)
class UserAdmin(UserAdmin, BaseModelAdmin):
    model = User
    form = UserChangeForm
    add_form = UserCreationForm
    change_password_form = AdminPasswordChangeForm

    list_display = ('id', 'first_name', 'last_name', 'phone_number', 'balance', 'role', 'detail_link')
    list_filter = ('role', 'is_active', 'is_staff')
    list_display_links = ('id', 'first_name')
    search_fields = ('first_name', 'last_name', 'phone_number')
    ordering = ('-date_joined',)
    inlines = (WorkScheduleInline,)
    list_per_page = 20

    fieldsets = (
        (None, {"fields": ("phone_number", "password")}),
        (
            _("Personal info"),
            {
                "fields": (
                    "first_name", "last_name", "birthdate", "gender", 'balance', 'profession',
                    "photo", 'role', 'show_in_search', 'inviter', 'is_invited')}),
        (
            _("Permissions"),
            {
                "fields": (
                    "is_active",
                    "is_staff",
                    "is_superuser",
                    "groups",
                    "user_permissions",
                ),
            },
        ),
        (_("Important dates"), {"fields": ("last_login", "date_joined")}),
    )

    add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": (
                    "phone_number",
                    "password1",
                    "password2",
                ),
            },
        ),
    )
