from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.contrib.auth import get_user_model
from django.utils import timezone

User = get_user_model()


class PayoutRequest(models.Model):
    STATUS_PENDING = 'pending'
    STATUS_APPROVED = 'approved'
    STATUS_REJECTED = 'rejected'
    STATUS_COMPLETED = 'completed'

    STATUS_CHOICES = [
        (STATUS_PENDING, 'Ожидает'),
        (STATUS_APPROVED, 'Одобрена'),
        (STATUS_REJECTED, 'Отклонена'),
        (STATUS_COMPLETED, 'Выполнена'),
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

    balance_updated = models.BooleanField(default=False, editable=False)

    class Meta:
        verbose_name = "Запрос на вывод средств"
        verbose_name_plural = "Запросы на вывод средств"
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.user} - {self.amount} ({self.method}) [{self.status}]"

    def save(self, *args, **kwargs):
        """
        Вся логика списания и возврата баланса реализована здесь.
        """
        with transaction.atomic():
            is_new = self._state.adding
            old_status = None
            old_balance_updated = self.balance_updated

            if not is_new:
                old = PayoutRequest.objects.select_for_update().get(pk=self.pk)
                old_status = old.status
                old_balance_updated = old.balance_updated

            if not old_balance_updated and self.status in [self.STATUS_APPROVED, self.STATUS_COMPLETED]:
                if self.user.balance < self.amount:
                    raise ValidationError("Недостаточно средств на балансе пользователя.")
                self.user.balance -= self.amount
                self.user.save(update_fields=['balance'])
                self.balance_updated = True

            elif old_balance_updated and self.status == self.STATUS_REJECTED and old_status != self.STATUS_REJECTED:
                self.user.balance += self.amount
                self.user.save(update_fields=['balance'])
                self.balance_updated = False

            if self.status != self.STATUS_PENDING and not self.processed_at:
                self.processed_at = timezone.now()

            super().save(*args, **kwargs)

    def clean(self):
        """
        Валидация при создании запроса
        """
        if self._state.adding and self.amount > self.user.balance:
            raise ValidationError("Недостаточно средств на балансе пользователя.")
