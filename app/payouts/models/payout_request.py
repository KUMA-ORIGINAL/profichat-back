from django.db import models
from django.contrib.auth import get_user_model

User = get_user_model()


class PayoutRequest(models.Model):
    STATUS_CHOICES = [
        ('pending', 'Ожидает'),
        ('approved', 'Одобрена'),
        ('rejected', 'Отклонена'),
        ('completed', 'Выполнена'),
    ]

    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="payouts",
        verbose_name="Пользователь"
    )
    method = models.ForeignKey(
        'PayoutMethod',
        on_delete=models.PROTECT,
        related_name='payouts',
        verbose_name="Способ вывода"
    )
    phone_number = models.CharField("Номер телефона", max_length=20)
    amount = models.DecimalField("Сумма", max_digits=10, decimal_places=2)
    status = models.CharField("Статус", max_length=50, choices=STATUS_CHOICES, default='pending')
    manager_comment = models.TextField("Комментарий менеджера", blank=True, null=True)
    created_at = models.DateTimeField("Дата создания", auto_now_add=True)
    processed_at = models.DateTimeField("Обработано", blank=True, null=True)

    def __str__(self):
        return f"{self.user} - {self.amount} ({self.method}) [{self.status}]"

    class Meta:
        verbose_name = "Запрос на вывод средств"
        verbose_name_plural = "Запросы на вывод средств"
        ordering = ['-created_at']