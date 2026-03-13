from django.db import models
from django.utils.translation import gettext_lazy as _

from common.models import BaseModel


class Organization(BaseModel):
    name = models.CharField(_("Название"), max_length=255, unique=True)
    is_active = models.BooleanField(_("Активна"), default=True)

    class Meta:
        verbose_name = _("Организация")
        verbose_name_plural = _("Организации")
        ordering = ("name",)

    def __str__(self):
        return self.name
