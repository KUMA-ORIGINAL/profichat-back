from django.conf import settings
from django.db import models

from common.models import BaseModel


class BlockedChat(BaseModel):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="blocked_chats",
        verbose_name="Пользователь",
    )
    chat = models.ForeignKey(
        "chat_access.Chat",
        on_delete=models.CASCADE,
        related_name="blocked_entries",
        verbose_name="Чат",
    )

    class Meta:
        verbose_name = "Чат в черном списке"
        verbose_name_plural = "Чаты в черном списке"
        constraints = [
            models.UniqueConstraint(fields=("user", "chat"), name="unique_blocked_chat_per_user"),
        ]
        indexes = [
            models.Index(fields=("user", "-created_at")),
            models.Index(fields=("chat",)),
        ]

    def __str__(self):
        return f"BlockedChat<{self.user_id}:{self.chat_id}>"
