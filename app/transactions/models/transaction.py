from django.db import models


class Transaction(models.Model):
    patient = models.ForeignKey('account.Patient', on_delete=models.CASCADE, verbose_name="Пациент")
    staff = models.ForeignKey('account.User', on_delete=models.CASCADE, verbose_name="Сотрудник")
    total_price = models.DecimalField(max_digits=10, decimal_places=2, verbose_name="Общая сумма")
    comment = models.TextField(blank=True, null=True, verbose_name="Комментарий")
    phone_number = models.CharField(max_length=20, verbose_name="Номер телефона")
    pay_method = models.CharField(
        max_length=50,
        choices=[('cash', 'Наличные'), ('bakai_bank', 'Bakai Bank')],
        verbose_name="Способ оплаты"
    )
    status = models.CharField(
        max_length=50,
        choices=[('paid', 'Оплачено'), ('pending', 'В ожидании'), ('failed', 'Не удалось')],
        verbose_name="Статус оплаты"
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Дата транзакции")

    organization = models.ForeignKey(
        'organizations.Organization',
        on_delete=models.CASCADE,
        verbose_name='Организация',
        related_name='transactions'
    )

    def __str__(self):
        return f"Транзакция {self.id} - {self.patient.first_name} {self.patient.last_name}"

    class Meta:
        verbose_name = "Транзакция"
        verbose_name_plural = "Транзакции"
        ordering = ['-created_at']
