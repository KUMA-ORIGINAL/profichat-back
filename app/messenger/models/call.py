import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone


class Call(models.Model):
    class Kind(models.TextChoices):
        AUDIO = "audio", "Аудио"
        VIDEO = "video", "Видео"

    class Status(models.TextChoices):
        RINGING = "ringing", "Звонит"
        ACCEPTED = "accepted", "Принят"
        DECLINED = "declined", "Отклонён"
        MISSED = "missed", "Пропущен"
        CANCELLED = "cancelled", "Отменён"
        BUSY = "busy", "Занято"
        ENDED = "ended", "Завершён"
        FAILED = "failed", "Ошибка"

    ACTIVE_STATUSES = (Status.RINGING, Status.ACCEPTED)

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    chat = models.ForeignKey(
        "chat_access.Chat", on_delete=models.CASCADE, related_name="calls", verbose_name="Чат"
    )
    caller = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name="calls_made", verbose_name="Звонящий",
    )
    callee = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name="calls_received", verbose_name="Принимающий",
    )
    kind = models.CharField(max_length=8, choices=Kind.choices, default=Kind.AUDIO, verbose_name="Вид")
    status = models.CharField(
        max_length=16, choices=Status.choices, default=Status.RINGING, db_index=True,
        verbose_name="Статус",
    )
    room_name = models.CharField(max_length=255, verbose_name="Комната LiveKit")
    created_at = models.DateTimeField(default=timezone.now, verbose_name="Начат")
    answered_at = models.DateTimeField(null=True, blank=True, verbose_name="Принят")
    ended_at = models.DateTimeField(null=True, blank=True, verbose_name="Завершён")
    end_reason = models.CharField(max_length=64, blank=True, default="", verbose_name="Причина завершения")
    duration_seconds = models.PositiveIntegerField(default=0, verbose_name="Длительность, с")

    class Meta:
        verbose_name = "Звонок"
        verbose_name_plural = "Звонки"
        ordering = ["-created_at"]

    def __str__(self):
        return f"Call {self.pk} ({self.status})"
