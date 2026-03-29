from django.conf import settings
from django.db import models

from common.models import BaseModel


class FavoriteChat(BaseModel):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="favorite_chats",
        verbose_name="Пользователь",
    )
    chat = models.ForeignKey(
        "chat_access.Chat",
        on_delete=models.CASCADE,
        related_name="favorites",
        verbose_name="Чат",
    )

    class Meta:
        verbose_name = "Избранный чат"
        verbose_name_plural = "Избранные чаты"
        constraints = [
            models.UniqueConstraint(fields=("user", "chat"), name="unique_favorite_chat_per_user"),
        ]
        indexes = [
            models.Index(fields=("user", "-created_at")),
            models.Index(fields=("chat",)),
        ]

    def __str__(self):
        return f"FavoriteChat<{self.user_id}:{self.chat_id}>"
