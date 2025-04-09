from django.db import models


class WorkSchedule(models.Model):
    MONDAY = 1
    TUESDAY = 2
    WEDNESDAY = 3
    THURSDAY = 4
    FRIDAY = 5
    SATURDAY = 6
    SUNDAY = 7
    DAY_CHOICES = [
        (MONDAY, 'Понедельник'),
        (TUESDAY, 'Вторник'),
        (WEDNESDAY, 'Среда'),
        (THURSDAY, 'Четверг'),
        (FRIDAY, 'Пятница'),
        (SATURDAY, 'Суббота'),
        (SUNDAY, 'Воскресенье'),
    ]

    user = models.ForeignKey(
        'User',
        on_delete=models.CASCADE,
        related_name='work_schedules',
        verbose_name='Пользователь'
    )
    day_of_week = models.PositiveSmallIntegerField(
        choices=DAY_CHOICES,
        verbose_name='День недели'
    )
    from_time = models.TimeField(verbose_name='Время начала')
    to_time = models.TimeField(verbose_name='Время окончания')

    class Meta:
        verbose_name = 'График работы'
        verbose_name_plural = 'Графики работы'
        unique_together = ('user', 'day_of_week')

    def __str__(self):
        return f'{self.get_day_of_week_display()} ({self.from_time} - {self.to_time})'