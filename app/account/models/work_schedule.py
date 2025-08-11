from django.db import models

from common.stream_client import chat_client


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

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        self.sync_work_schedule_to_stream()

    def delete(self, *args, **kwargs):
        user_id = self.user_id
        super().delete(*args, **kwargs)
        self.sync_work_schedule_to_stream(user_id=user_id)

    def sync_work_schedule_to_stream(self, user_id=None):
        """
        Собирает все расписания пользователя и отправляет их в getstream
        """
        user = self.user if hasattr(self, 'user') else None
        user_id = user_id or (user.id if user else None)
        if not user_id:
            return

        schedules = WorkSchedule.objects.filter(user_id=user_id)
        schedule_data = []
        for i, ws in enumerate(schedules):
            schedule_data.append({
                "id": ws.id,
                "dayOfWeek": ws.day_of_week,
                "fromTime": ws.from_time.isoformat(),  # например, "09:00:00"
                "toTime": ws.to_time.isoformat(),
            })

        try:
            chat_client.upsert_user({
                "id": str(user_id),
                "work_schedule": schedule_data,
            })
        except Exception as e:
            import logging
            logging.error(f"Ошибка при отправке work_schedule в GetStream: {e}")