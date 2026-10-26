from django.conf import settings
from django.db import models

from common.models import BaseModel


class VoipDevice(BaseModel):
    """PushKit-токен iOS-устройства для VoIP-пушей о входящих звонках."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name="voip_devices", verbose_name="Пользователь",
    )
    token = models.CharField(max_length=255, unique=True, verbose_name="PushKit-токен")
    bundle_id = models.CharField(max_length=255, verbose_name="Bundle ID")
    active = models.BooleanField(default=True, verbose_name="Активно")

    class Meta:
        verbose_name = "VoIP-устройство"
        verbose_name_plural = "VoIP-устройства"

    def __str__(self):
        return f"VoipDevice {self.pk} user={self.user_id}"
