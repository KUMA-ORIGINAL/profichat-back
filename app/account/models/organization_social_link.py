from django.db import models
from django.utils.translation import gettext_lazy as _

from common.models import BaseModel


class OrganizationSocialLink(BaseModel):
    organization = models.ForeignKey(
        'Organization',
        on_delete=models.CASCADE,
        related_name='social_links',
        verbose_name=_("Организация"),
    )
    social_network = models.ForeignKey(
        'SocialNetwork',
        on_delete=models.PROTECT,
        related_name='organization_links',
        verbose_name=_("Социальная сеть"),
    )
    url = models.CharField(_("Ссылка / username"), max_length=500)

    class Meta:
        verbose_name = _("Соцсеть организации")
        verbose_name_plural = _("Соцсети организаций")
        unique_together = ('organization', 'social_network')

    def __str__(self):
        return f"{self.organization.name} — {self.social_network.name}: {self.url}"
