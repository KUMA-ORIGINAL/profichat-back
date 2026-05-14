from django.db import models
from django.core.validators import MaxValueValidator, MinValueValidator
from django.utils.translation import gettext_lazy as _

from common.models import BaseModel


class Organization(BaseModel):
    name = models.CharField(_("Название"), max_length=255, unique=True)
    logo = models.ImageField(
        _("Логотип"),
        upload_to="organizations/logos/",
        blank=True,
        null=True,
    )
    description = models.TextField(_("Описание"), blank=True, null=True)
    category = models.CharField(_("Категория"), max_length=255, blank=True, null=True)
    rating = models.DecimalField(
        _("Рейтинг"),
        max_digits=2,
        decimal_places=1,
        default=0.0,
        validators=[MinValueValidator(0.0), MaxValueValidator(5.0)],
    )
    reviews_count = models.PositiveIntegerField(_("Количество отзывов"), default=0)
    is_active = models.BooleanField(_("Активна"), default=True)

    class Meta:
        verbose_name = _("Организация")
        verbose_name_plural = _("Организации")
        ordering = ("name",)

    def __str__(self):
        return self.name
