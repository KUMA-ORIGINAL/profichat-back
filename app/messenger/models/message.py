from django.conf import settings
from django.contrib.postgres.indexes import GinIndex, OpClass
from django.db import models
from django.db.models import F, Q
from django.db.models.functions import Upper
from django.utils import timezone


class Message(models.Model):
    class Type(models.TextChoices):
        REGULAR = "regular", "Обычное"
        SYSTEM = "system", "Системное"
        CALL = "call", "Звонок"

    chat = models.ForeignKey(
        "chat_access.Chat", on_delete=models.CASCADE, related_name="messages",
        verbose_name="Чат",
    )
    sender = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="messenger_messages", verbose_name="Отправитель",
    )
    type = models.CharField(
        max_length=16, choices=Type.choices, default=Type.REGULAR, verbose_name="Тип"
    )
    custom_type = models.CharField(
        max_length=64, blank=True, default="", verbose_name="Подтип системного сообщения"
    )
    text = models.TextField(blank=True, default="", verbose_name="Текст")
    reply_to = models.ForeignKey(
        "self", on_delete=models.SET_NULL, null=True, blank=True, related_name="replies",
        verbose_name="Ответ на сообщение",
    )
    call = models.ForeignKey(
        "messenger.Call", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="messages", verbose_name="Звонок",
    )
    extra_data = models.JSONField(default=dict, blank=True, verbose_name="Доп. данные")
    client_msg_id = models.UUIDField(
        null=True, blank=True, verbose_name="Клиентский ID (идемпотентность)"
    )
    stream_id = models.CharField(
        max_length=255, null=True, blank=True, unique=True,
        verbose_name="ID сообщения в GetStream",
    )
    edited_at = models.DateTimeField(null=True, blank=True, verbose_name="Изменено")
    deleted_at = models.DateTimeField(null=True, blank=True, verbose_name="Удалено")
    # не auto_now_add: импорт из GetStream сохраняет исходное время
    created_at = models.DateTimeField(
        default=timezone.now, db_index=False, verbose_name="Дата создания"
    )

    class Meta:
        verbose_name = "Сообщение"
        verbose_name_plural = "Сообщения"
        indexes = [
            models.Index(fields=["chat", "-created_at", "-id"], name="msg_chat_created_id_idx"),
            # поиск по тексту: Django строит icontains как UPPER(text) LIKE UPPER('%q%') — индекс по тому же
            # выражению; chat_id первым (btree_gin) — поиск сужается чатами пользователя, в том числе
            # для 2-символьных запросов, где у pg_trgm нет триграмм
            GinIndex(
                F("chat"),
                OpClass(Upper("text"), name="gin_trgm_ops"),
                name="msg_chat_text_upper_trgm_idx",
                condition=Q(type="regular", deleted_at__isnull=True),
            ),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["chat", "sender", "client_msg_id"],
                condition=Q(client_msg_id__isnull=False),
                name="uniq_msg_chat_sender_client_msg_id",
            ),
        ]

    def __str__(self):
        return f"Message {self.pk} в чате {self.chat_id}"
