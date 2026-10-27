from django.conf import settings
from django.db import models

from common.models import BaseModel


class ChatMember(BaseModel):
    """Состояние участника чата (по 2 строки на чат)."""

    class Role(models.TextChoices):
        CLIENT = "client", "Клиент"
        SPECIALIST = "specialist", "Специалист"

    chat = models.ForeignKey(
        "chat_access.Chat", on_delete=models.CASCADE, related_name="members",
        verbose_name="Чат",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name="chat_memberships", verbose_name="Пользователь",
    )
    role = models.CharField(max_length=16, choices=Role.choices, verbose_name="Роль")
    last_read_message_id = models.BigIntegerField(
        null=True, blank=True, verbose_name="ID последнего прочитанного сообщения"
    )
    unread_count = models.PositiveIntegerField(default=0, verbose_name="Непрочитанных")
    muted = models.BooleanField(default=False, verbose_name="Без уведомлений")
    pinned_at = models.DateTimeField(null=True, blank=True, verbose_name="Закреплён")

    class Meta:
        verbose_name = "Участник чата"
        verbose_name_plural = "Участники чатов"
        constraints = [
            models.UniqueConstraint(fields=["chat", "user"], name="uniq_chatmember_chat_user"),
        ]

    def __str__(self):
        return f"{self.user_id} в чате {self.chat_id} ({self.role})"
