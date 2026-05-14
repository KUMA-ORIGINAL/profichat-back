from django.db import models
from django.utils.translation import gettext_lazy as _

from common.models import BaseModel


class OrganizationGalleryImage(BaseModel):
    organization = models.ForeignKey(
        'Organization',
        on_delete=models.CASCADE,
        related_name='gallery_images',
        verbose_name=_("Организация"),
    )
    image = models.ImageField(
        _("Изображение"),
        upload_to='organizations/gallery/',
    )
    order = models.PositiveSmallIntegerField(_("Порядок"), default=0)

    class Meta:
        verbose_name = _("Фото галереи организации")
        verbose_name_plural = _("Фото галереи организаций")
        ordering = ('order', 'id')

    def __str__(self):
        return f"{self.organization.name} — фото {self.id}"
