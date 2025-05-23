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
        ('success', 'Успешно'),
        ('cancelled', 'Отменён'),
    ]

    duration_hours = models.PositiveIntegerField(
        verbose_name="Срок действия (в часах)",
        blank=True,
        null=True,
    )
    tariff_type = models.CharField(
        max_length=255,
        choices=TARIFF_TYPE_CHOICES,
        verbose_name="Тип пакета",
        blank=True,
        null=True,
    )
    price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        verbose_name="Стоимость",
        blank=True,
        default=0,
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

    tariff = models.ForeignKey(
        'Tariff',
        on_delete=models.PROTECT,
        verbose_name="Тариф"
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
    chat = models.ForeignKey(
        'Chat',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='access_orders'
    )

    class Meta:
        ordering = ['-created_at']
        verbose_name = "Заказ доступа"
        verbose_name_plural = "Заказы доступа"

    def save(self, *args, **kwargs):
        is_creating = self._state.adding
        if is_creating:
            self.duration_hours = self.tariff.duration_hours
            self.tariff_type = self.tariff.tariff_type
            self.price = self.tariff.price
        super().save(*args, **kwargs)

    def activate(self):
        """Активировать доступ (после оплаты)"""
        self.activated_at = timezone.now()
        # Если тариф основан на днях — переводим в часы
        self.expires_at = self.activated_at + timedelta(hours=self.tariff.duration_hours)
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
