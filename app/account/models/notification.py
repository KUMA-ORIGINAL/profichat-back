from django.conf import settings
from django.db import models

from common.models import BaseModel


class Notification(BaseModel):
    TYPE_SYSTEM = "system"
    TYPE_PAYMENT_SUCCESS = "payment_success"
    TYPE_CHAT_INVITE = "chat_invite"
    TYPE_APPLICATION_ACCEPTED = "application_accepted"

    TYPE_CHOICES = (
        (TYPE_SYSTEM, "Системное"),
        (TYPE_PAYMENT_SUCCESS, "Успешная оплата"),
        (TYPE_CHAT_INVITE, "Приглашение в чат"),
        (TYPE_APPLICATION_ACCEPTED, "Заявка одобрена"),
    )

    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="notifications",
        verbose_name="Получатель",
    )
    notification_type = models.CharField(
        max_length=50,
        choices=TYPE_CHOICES,
        default=TYPE_SYSTEM,
        db_index=True,
        verbose_name="Тип уведомления",
    )
    title = models.CharField(max_length=255, verbose_name="Заголовок")
    message = models.TextField(verbose_name="Сообщение")
    payload = models.JSONField(default=dict, blank=True, verbose_name="Доп. данные")
    is_read = models.BooleanField(default=False, db_index=True, verbose_name="Прочитано")
    read_at = models.DateTimeField(blank=True, null=True, verbose_name="Дата прочтения")
    pushed_at = models.DateTimeField(blank=True, null=True, verbose_name="Дата push-отправки")

    class Meta:
        verbose_name = "Уведомление"
        verbose_name_plural = "Уведомления"
        ordering = ("-created_at",)
        indexes = [
            models.Index(fields=("recipient", "is_read", "-created_at")),
            models.Index(fields=("recipient", "notification_type", "-created_at")),
        ]

    def __str__(self):
        return f"Notification<{self.id}> to {self.recipient_id}: {self.title}"
