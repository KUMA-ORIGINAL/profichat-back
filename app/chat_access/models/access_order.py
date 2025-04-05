from django.db import models
from django.utils import timezone
from datetime import timedelta
from django.contrib.auth import get_user_model

User = get_user_model()


class AccessOrder(models.Model):
    TARIFF_TYPE_CHOICES = [
        ('free', 'Бесплатный'),
        ('paid', 'Платный'),
    ]

    PAYMENT_STATUS_CHOICES = [
        ('pending', 'Ожидает оплаты'),
        ('paid', 'Успешно'),
        ('cancelled', 'Отменён'),
    ]

    tariff = models.ForeignKey(
        'Tariff',
        on_delete=models.PROTECT,
        verbose_name="Тариф"
    )
    duration_hours = models.PositiveIntegerField(
        default=24,
        verbose_name="Срок действия (в часах)"
    )
    tariff_type = models.CharField(
        max_length=255,
        choices=TARIFF_TYPE_CHOICES,
        default='paid',
        verbose_name="Тип пакета"
    )
    price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        verbose_name="Стоимость"
    )
    payment_status = models.CharField(
        max_length=20,
        choices=PAYMENT_STATUS_CHOICES,
        default='pending',
        verbose_name="Статус оплаты"
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name="Дата инициации"
    )
    activated_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="Начало пакета"
    )
    expires_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="Конец пакета"
    )

    client = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="access_orders",
        verbose_name="Пациент"
    )
    specialist = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="orders_received",
        verbose_name="Специалист"
    )

    class Meta:
        ordering = ['-created_at']
        verbose_name = "Заказ доступа"
        verbose_name_plural = "Заказы доступа"

    def activate(self):
        """Активировать доступ (после оплаты)"""
        self.activated_at = timezone.now()
        # Если тариф основан на днях — переводим в часы
        self.expires_at = self.activated_at + timedelta(hours=self.tariff.duration_hours)
        self.payment_status = 'paid'
        self.save()

    @property
    def is_active(self):
        """Есть ли сейчас доступ"""
        if self.payment_status != 'paid' or not self.expires_at:
            return False
        return self.expires_at > timezone.now()

    def __str__(self):
        status = "Активен" if self.is_active else "Не активен"
        return f"{self.client} → {self.specialist} | {self.tariff.name} | {status}"
