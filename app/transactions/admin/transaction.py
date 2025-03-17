from django.contrib import admin

from import_export.admin import ExportActionModelAdmin
from unfold.admin import TabularInline
from unfold.contrib.filters.admin import RangeDateTimeFilter
from unfold.contrib.import_export.forms import ExportForm

from account.models import ROLE_ADMIN, ROLE_DOCTOR, ROLE_ACCOUNTANT
from ..models import Transaction, TransactionService
from common.admin import BaseModelAdmin
from ..resources import TransactionResource


class TransactionServiceInline(TabularInline):
    model = TransactionService
    extra = 1
    fields = ("service", "service_price")
    readonly_fields = ("service_price",)


@admin.register(Transaction)
class TransactionAdmin(BaseModelAdmin, ExportActionModelAdmin):
    search_fields = ("patient__first_name", "patient__last_name", "staff__first_name", "staff__last_name",)
    ordering = ("-created_at",)
    readonly_fields = ("created_at",)
    date_hierarchy = "created_at"
    inlines = [TransactionServiceInline]
    resource_classes = (TransactionResource,)
    list_filter_submit = True

    export_form_class = ExportForm

    fieldsets = (
        (None, {
            "fields": ("patient", "staff", "total_price", "comment", "phone_number", "pay_method", "status", "organization")
        }),
        ('Дополнительная информация', {
            "fields": ("created_at",),
            "classes": ("collapse",)
        }),
    )

    def get_list_filter(self, request):
        list_filter = ("pay_method", "status", "organization", ("created_at", RangeDateTimeFilter))
        if request.user.is_superuser:
            pass
        elif request.user.role in (ROLE_ADMIN, ROLE_DOCTOR, ROLE_ACCOUNTANT):
            list_filter = ("pay_method", "status", ("created_at", RangeDateTimeFilter))
        return list_filter

    def get_list_display(self, request):
        list_display = (
            "id", "patient", "staff", "total_price", "pay_method", "status", "created_at", "organization", 'detail_link')
        if request.user.is_superuser:
            pass
        elif request.user.role in (ROLE_ADMIN, ROLE_DOCTOR, ROLE_ACCOUNTANT):
            list_display = (
                "patient", "staff", "total_price", "pay_method", "status", "created_at", 'detail_link')
        return list_display

    def get_fieldsets(self, request, obj=None):
        fieldsets = (
            (None, {
                "fields": (
                "patient", "staff", "total_price", "comment", "phone_number", "pay_method", "status", "organization")
            }),
            ('Дополнительная информация', {
                "fields": ("created_at",),
                "classes": ("collapse",)
            }),
        )
        if request.user.is_superuser:
            pass
        elif request.user.role in (ROLE_ADMIN, ROLE_DOCTOR, ROLE_ACCOUNTANT):
            fieldsets[0][1]['fields'] = (
                "patient", "staff", "total_price", "comment", "phone_number", "pay_method", "status")
        return fieldsets


    def save_model(self, request, obj, form, change):
        if request.user.role == ROLE_ADMIN:
            obj.organization = request.user.organization
        super().save_model(request, obj, form, change)

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        if request.user.is_superuser:
            return qs
        elif request.user.role in (ROLE_ADMIN, ROLE_ACCOUNTANT):
            return qs.filter(organization=request.user.organization)
        elif request.user.role == ROLE_DOCTOR:
            return qs.filter(organization=request.user.organization, staff=request.user)
