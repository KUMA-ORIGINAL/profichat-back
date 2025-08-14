from django.db import models
from django.contrib.auth import get_user_model

User = get_user_model()


class Tariff(models.Model):
    TARIFF_TYPE_CHOICES = [
        ('free', 'Бесплатный'),
        ('paid', 'Платный'),
    ]

    name = models.CharField(
        max_length=255,
        verbose_name="Название пакета"
    )
    price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        verbose_name="Стоимость"
    )
    duration_hours = models.PositiveIntegerField(
        default=24,
        verbose_name="Срок действия (в часах)"
    )
    is_active = models.BooleanField(
        default=False,
        verbose_name="Активный"
    )
    is_archive = models.BooleanField(default=False)
    tariff_type = models.CharField(
        max_length=255,
        choices=TARIFF_TYPE_CHOICES,
        default='paid',
        verbose_name="Тип пакета"
    )

    specialist = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="tariffs",
        verbose_name="Специалист"
    )

    def __str__(self):
        return f"{self.name} — {self.specialist.get_full_name() or self.specialist.username}"

    class Meta:
        verbose_name = "Тариф"
        verbose_name_plural = "Тарифы"

    def delete(self, using=None, keep_parents=False):
        self.is_archive = True
        self.save(update_fields=['is_active'])
