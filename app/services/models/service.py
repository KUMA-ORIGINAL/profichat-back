from django.db import models


class Service(models.Model):
    name = models.CharField(
        max_length=255,
        verbose_name='Название услуги'
    )
    description = models.TextField(
        blank=True,
        null=True,
        verbose_name='Описание услуги'
    )
    price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        verbose_name='Цена'
    )
    photo = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        verbose_name='Фото услуги'
    )
    organization = models.ForeignKey(
        'organizations.Organization',
        on_delete=models.CASCADE,
        verbose_name='Организация',
        related_name='services'
    )

    def __str__(self):
        return self.name

    class Meta:
        verbose_name = 'Услуга'
        verbose_name_plural = 'Услуги'