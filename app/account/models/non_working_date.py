from django.db import models
from django.utils import timezone


class NonWorkingDateQuerySet(models.QuerySet):
    def upcoming(self):
        return self.filter(date__gte=timezone.localdate())


class NonWorkingDate(models.Model):
    """Разовый нерабочий день вне недельного графика (отпуск, больничный и т.п.)."""

    user = models.ForeignKey(
        'User',
        on_delete=models.CASCADE,
        related_name='non_working_dates',
        verbose_name='Пользователь',
    )
    date = models.DateField(verbose_name='Дата')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='Создано')

    objects = NonWorkingDateQuerySet.as_manager()

    class Meta:
        verbose_name = 'Нерабочая дата'
        verbose_name_plural = 'Нерабочие даты'
        ordering = ('date',)
        constraints = [
            models.UniqueConstraint(fields=('user', 'date'), name='unique_user_non_working_date'),
        ]

    def __str__(self):
        return f'{self.date:%d.%m.%Y} — нерабочий день'
