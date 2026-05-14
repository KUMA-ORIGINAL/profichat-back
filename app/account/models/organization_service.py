from django.db import models
from django.utils.translation import gettext_lazy as _

from common.models import BaseModel


class OrganizationService(BaseModel):
    organization = models.ForeignKey(
        'Organization',
        on_delete=models.CASCADE,
        related_name='services',
        verbose_name=_("Организация"),
    )
    name = models.CharField(_("Услуга"), max_length=255)

    class Meta:
        verbose_name = _("Услуга организации")
        verbose_name_plural = _("Услуги организаций")
        ordering = ('id',)

    def __str__(self):
        return f"{self.organization.name} — {self.name}"
