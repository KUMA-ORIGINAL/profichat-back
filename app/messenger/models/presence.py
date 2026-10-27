from django.conf import settings
from django.db import models


class UserPresence(models.Model):
    """
    Последняя активность пользователя в мессенджере (для `companion.lastActiveAt`).

    Отдельная таблица, а не поле User: User.save синхронизирует пользователя с GetStream.
    Обновляется не чаще раза в минуту (services.presence.touch).
    """

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, primary_key=True,
        related_name="messenger_presence", verbose_name="Пользователь",
    )
    last_active_at = models.DateTimeField(verbose_name="Последняя активность")

    class Meta:
        verbose_name = "Активность пользователя"
        verbose_name_plural = "Активность пользователей"

    def __str__(self):
        return f"{self.user_id}: {self.last_active_at}"
