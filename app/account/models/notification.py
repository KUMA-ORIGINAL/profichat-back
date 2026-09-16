from django.conf import settings
from django.db import models

from common.models import BaseModel


class Notification(BaseModel):
    TYPE_SYSTEM = "system"
    TYPE_PAYMENT_SUCCESS = "payment_success"
    TYPE_CHAT_INVITE = "chat_invite"
    TYPE_APPLICATION_ACCEPTED = "application_accepted"
    TYPE_APPLICATION_REJECTED = "application_rejected"
    TYPE_PROFESSION_REQUEST_APPROVED = "profession_request_approved"
    TYPE_PROFESSION_REQUEST_REJECTED = "profession_request_rejected"
    TYPE_ERKINAI = "erkinai"

    TYPE_CHOICES = (
        (TYPE_SYSTEM, "Системное"),
        (TYPE_PAYMENT_SUCCESS, "Успешная оплата"),
        (TYPE_CHAT_INVITE, "Приглашение в чат"),
        (TYPE_APPLICATION_ACCEPTED, "Заявка одобрена"),
        (TYPE_APPLICATION_REJECTED, "Заявка отклонена"),
        (TYPE_PROFESSION_REQUEST_APPROVED, "Профессия добавлена"),
        (TYPE_PROFESSION_REQUEST_REJECTED, "Заявка на профессию отклонена"),
        (TYPE_ERKINAI, "Из ErkinAI"),
    )

    # Откуда уведомление взялось. Приложению это нужно раньше типа:
    # своё оно откроет внутри себя, чужое — в разделе CRM. Поле не хранится:
    # источник однозначно следует из типа, а дублирующая колонка рано или
    # поздно разошлась бы с ним.
    SOURCE_PROFICHAT = "profichat"
    SOURCE_ERKINAI = "erkinai"

    ERKINAI_TYPES = frozenset({TYPE_ERKINAI})

    @classmethod
    def source_for_type(cls, notification_type):
        """``profichat`` или ``erkinai`` — кто породил уведомление этого типа."""
        if notification_type in cls.ERKINAI_TYPES:
            return cls.SOURCE_ERKINAI
        return cls.SOURCE_PROFICHAT

    @property
    def source(self):
        return self.source_for_type(self.notification_type)

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
