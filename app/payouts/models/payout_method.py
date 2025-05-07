from django.db import models


class PayoutMethod(models.Model):
    name = models.CharField(
        max_length=255,
        verbose_name="Название способа"
    )
    is_active = models.BooleanField(
        default=True,
        verbose_name="Активен"
    )
    logo = models.ImageField(
        upload_to='payout_logos/',
        null=True,
        blank=True,
        verbose_name="Логотип"
    )

    def __str__(self):
        return self.name

    class Meta:
        verbose_name = "Способ вывода"
        verbose_name_plural = "Способы вывода"
