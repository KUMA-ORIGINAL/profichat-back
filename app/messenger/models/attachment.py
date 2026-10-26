import uuid

from django.conf import settings
from django.db import models

from common.models import BaseModel


class Attachment(BaseModel):
    class Kind(models.TextChoices):
        IMAGE = "image", "Изображение"
        VIDEO = "video", "Видео"
        FILE = "file", "Файл"
        VOICE = "voice", "Голосовое"

    class Status(models.TextChoices):
        PENDING = "pending", "Ожидает загрузки"
        READY = "ready", "Готово"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    uploader = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name="messenger_attachments", verbose_name="Загрузил",
    )
    chat = models.ForeignKey(
        "chat_access.Chat", on_delete=models.CASCADE, related_name="attachments",
        verbose_name="Чат",
    )
    message = models.ForeignKey(
        "messenger.Message", on_delete=models.CASCADE, null=True, blank=True,
        related_name="attachments", verbose_name="Сообщение",
    )
    kind = models.CharField(max_length=16, choices=Kind.choices, verbose_name="Тип")
    object_key = models.CharField(max_length=512, verbose_name="Ключ объекта в хранилище")
    file_name = models.CharField(max_length=255, blank=True, default="", verbose_name="Имя файла")
    mime_type = models.CharField(max_length=127, blank=True, default="", verbose_name="MIME-тип")
    size = models.BigIntegerField(default=0, verbose_name="Размер, байт")
    width = models.PositiveIntegerField(null=True, blank=True, verbose_name="Ширина")
    height = models.PositiveIntegerField(null=True, blank=True, verbose_name="Высота")
    duration_ms = models.PositiveIntegerField(null=True, blank=True, verbose_name="Длительность, мс")
    waveform = models.JSONField(null=True, blank=True, verbose_name="Waveform")
    status = models.CharField(
        max_length=16, choices=Status.choices, default=Status.PENDING, verbose_name="Статус"
    )

    class Meta:
        verbose_name = "Вложение"
        verbose_name_plural = "Вложения"
        indexes = [
            models.Index(fields=["status", "created_at"], name="att_status_created_idx"),
        ]

    def __str__(self):
        return f"Attachment {self.pk} ({self.kind})"
