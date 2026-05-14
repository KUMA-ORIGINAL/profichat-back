from django.db import models
from django.utils.translation import gettext_lazy as _

from common.models import BaseModel


class SocialNetwork(BaseModel):
    name = models.CharField(_("Название"), max_length=100, unique=True)
    logo = models.ImageField(_("Лого"), upload_to='social_networks/logos/', blank=True, null=True)

    class Meta:
        verbose_name = _("Социальная сеть")
        verbose_name_plural = _("Социальные сети")
        ordering = ('name',)

    def __str__(self):
        return self.name
