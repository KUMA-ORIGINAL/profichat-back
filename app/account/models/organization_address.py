from django.db import models
from django.utils.translation import gettext_lazy as _

from common.models import BaseModel


class OrganizationAddress(BaseModel):
    organization = models.ForeignKey(
        'Organization',
        on_delete=models.CASCADE,
        related_name='addresses',
        verbose_name=_("Организация"),
    )
    address = models.CharField(_("Адрес"), max_length=500)
    is_primary = models.BooleanField(_("Основной адрес"), default=False)

    class Meta:
        verbose_name = _("Адрес организации")
        verbose_name_plural = _("Адреса организаций")
        ordering = ('-is_primary', 'id')

    def __str__(self):
        return f"{self.organization.name} — {self.address}"
