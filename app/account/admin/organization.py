from django.contrib import admin
from django.utils.safestring import mark_safe
from unfold.admin import TabularInline

from common.admin import BaseModelAdmin
from ..models import (
    Organization,
    OrganizationAddress,
    OrganizationWorkSchedule,
    OrganizationSocialLink,
    OrganizationService,
    OrganizationGalleryImage,
    SocialNetwork,
)


class OrganizationAddressInline(TabularInline):
    model = OrganizationAddress
    extra = 1


class OrganizationWorkScheduleInline(TabularInline):
    model = OrganizationWorkSchedule
    extra = 0


class OrganizationSocialLinkInline(TabularInline):
    model = OrganizationSocialLink
    extra = 1


class OrganizationServiceInline(TabularInline):
    model = OrganizationService
    extra = 1


class OrganizationGalleryImageInline(TabularInline):
    model = OrganizationGalleryImage
    extra = 1


@admin.register(SocialNetwork)
class SocialNetworkAdmin(BaseModelAdmin):
    list_display = ("id", "name", "logo", "created_at")
    search_fields = ("name",)


@admin.register(Organization)
class OrganizationAdmin(BaseModelAdmin):
    list_display = ("id", "name", "category", "display_logo", "rating", "reviews_count", "is_active", "created_at", "detail_link")
    list_display_links = ("id", "name")
    search_fields = ("name", "description", "category")
    list_filter = ("is_active", "created_at")
    inlines = [
        OrganizationAddressInline,
        OrganizationWorkScheduleInline,
        OrganizationSocialLinkInline,
        OrganizationServiceInline,
        OrganizationGalleryImageInline,
    ]

    def display_logo(self, obj):
        if obj.logo:
            return mark_safe(f'<img src="{obj.logo.url}" width="50" height="50" />')
        return "-"

    display_logo.short_description = "Логотип"
