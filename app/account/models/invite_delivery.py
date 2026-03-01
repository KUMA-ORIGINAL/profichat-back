from django.contrib.auth import get_user_model
from django.db import models

from common.models import BaseModel

User = get_user_model()


class InviteDelivery(BaseModel):
    CHANNEL_SMS = "sms"
    CHANNEL_PUSH = "push"
    CHANNEL_CHOICES = (
        (CHANNEL_SMS, "SMS"),
        (CHANNEL_PUSH, "Push"),
    )

    STATUS_SENT = "sent"
    STATUS_FAILED = "failed"
    STATUS_CHOICES = (
        (STATUS_SENT, "Отправлено"),
        (STATUS_FAILED, "Ошибка"),
    )

    specialist = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="invite_deliveries_as_specialist",
        verbose_name="Специалист",
    )
    client = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="invite_deliveries_as_client",
        verbose_name="Клиент",
    )
    chat = models.ForeignKey(
        "chat_access.Chat",
        on_delete=models.CASCADE,
        related_name="invite_deliveries",
        verbose_name="Чат",
    )
    channel = models.CharField(
        max_length=10,
        choices=CHANNEL_CHOICES,
        verbose_name="Канал доставки",
    )
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        verbose_name="Статус доставки",
    )
    is_new_client = models.BooleanField(
        default=False,
        verbose_name="Новый клиент",
    )
    provider_message_id = models.CharField(
        max_length=255,
        blank=True,
        default="",
        verbose_name="ID сообщения у провайдера",
    )
    provider_status = models.CharField(
        max_length=255,
        blank=True,
        default="",
        verbose_name="Статус провайдера",
    )
    error_message = models.TextField(
        blank=True,
        default="",
        verbose_name="Текст ошибки",
    )
    metadata = models.JSONField(
        default=dict,
        blank=True,
        verbose_name="Дополнительные данные",
    )

    class Meta:
        ordering = ("-created_at",)
        verbose_name = "Доставка приглашения"
        verbose_name_plural = "Доставки приглашений"

    def __str__(self):
        return f"InviteDelivery #{self.id} ({self.channel}, {self.status})"
