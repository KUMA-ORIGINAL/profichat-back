from django.db import models

from common.models import BaseModel


class PushDeviceStatus(BaseModel):
    """Результат последней попытки доставки push на конкретное устройство.

    Нужен, чтобы клиент и поддержка видели, почему пуши не доходят:
    push_notifications сам деактивирует устройство при ошибке токена,
    но нигде не сохраняет причину.
    """

    device = models.OneToOneField(
        "push_notifications.GCMDevice",
        on_delete=models.CASCADE,
        related_name="delivery_status",
        verbose_name="Устройство",
    )
    last_success_at = models.DateTimeField("Последняя успешная отправка", null=True, blank=True)
    last_failure_at = models.DateTimeField("Последняя неудачная отправка", null=True, blank=True)
    last_error_code = models.CharField("Код последней ошибки", max_length=64, blank=True, default="")
    last_error_message = models.TextField("Текст последней ошибки", blank=True, default="")
    deactivated_at = models.DateTimeField("Когда токен признан нерабочим", null=True, blank=True)

    class Meta:
        verbose_name = "Состояние push-устройства"
        verbose_name_plural = "Состояния push-устройств"

    def __str__(self):
        return f"PushDeviceStatus<device={self.device_id}>"
