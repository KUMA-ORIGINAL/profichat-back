from django.db import models
from django.contrib.auth import get_user_model


User = get_user_model()


class Chat(models.Model):
    client = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name='chats_as_client'
    )
    specialist = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name='chats_as_specialist'
    )
    channel_id = models.CharField(
        max_length=255, unique=True, verbose_name='Channel ID в GetStream'
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('client', 'specialist')
        ordering = ['-created_at']
        verbose_name = 'Чат'
        verbose_name_plural = 'Чаты'

    def __str__(self):
        return f'{self.client} ↔ {self.specialist}'
