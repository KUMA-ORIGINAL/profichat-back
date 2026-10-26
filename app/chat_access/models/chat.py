from django.db import models
from django.contrib.auth import get_user_model

from common.models import BaseModel

User = get_user_model()


class Chat(BaseModel):
    client = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name='chats_as_client'
    )
    specialist = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name='chats_as_specialist'
    )
    channel_id = models.CharField(
        max_length=255, unique=True, verbose_name='Публичный ID канала'
    )
    specialist_note = models.TextField(
        blank=True, null=True, verbose_name='Заметка специалиста о клиенте'
    )
    client_can_send_voice = models.BooleanField(
        default=True,
        verbose_name="Клиент может отправлять голосовые"
    )

    deleted_by_client_at = models.DateTimeField(
        blank=True,
        null=True,
        db_index=True,
    )
    deleted_by_specialist_at = models.DateTimeField(
        blank=True,
        null=True,
        db_index=True,
    )

    last_message = models.ForeignKey(
        'messenger.Message',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='+',
        verbose_name='Последнее сообщение',
    )
    last_message_at = models.DateTimeField(
        null=True,
        blank=True,
        db_index=True,
        verbose_name='Время последнего сообщения',
    )

    class Meta:
        unique_together = ('client', 'specialist')
        ordering = ['-created_at']
        verbose_name = 'Чат'
        verbose_name_plural = 'Чаты'

    def __str__(self):
        return f'{self.client} ↔ {self.specialist}'

    def member_for(self, user):
        """ChatMember пользователя в этом чате или None, если он не участник."""
        return self.members.filter(user_id=user.pk).first()
