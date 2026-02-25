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
    from_time = models.TimeField(verbose_name='Время начала', null=True, blank=True)
    to_time = models.TimeField(verbose_name='Время окончания', null=True, blank=True)
    is_day_off = models.BooleanField(default=False, verbose_name='Выходной')
    is_round_the_clock = models.BooleanField(default=False, verbose_name='Круглосуточно')

    class Meta:
        verbose_name = 'График работы'
        verbose_name_plural = 'Графики работы'
        unique_together = ('user', 'day_of_week')

    def __str__(self):
        if self.is_day_off:
            return f'{self.get_day_of_week_display()} — выходной'
        if self.is_round_the_clock:
            return f'{self.get_day_of_week_display()} — круглосуточно'
        return f'{self.get_day_of_week_display()} ({self.from_time} - {self.to_time})'