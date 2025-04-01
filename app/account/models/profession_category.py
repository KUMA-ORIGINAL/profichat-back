from django.db import models
from django.utils.translation import gettext_lazy as _


class ProfessionCategory(models.Model):
    name = models.CharField(_("Название категории"), max_length=255)
    photo = models.ImageField(_("Фото"), upload_to="profession_categories/", blank=True, null=True)
    parent = models.ForeignKey(
        'self',  # ссылка на ту же самую модель
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='subcategories',
        verbose_name='Родительская категория'
    )

    class Meta:
        verbose_name = _("Категория специальности")
        verbose_name_plural = _("Категории специальностей")

    def __str__(self):
        return self.name
