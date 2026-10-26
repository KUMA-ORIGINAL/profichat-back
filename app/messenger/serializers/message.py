from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from messenger.models import Message
from messenger.serializers.attachment import AttachmentSerializer


class ReplyToSerializer(serializers.ModelSerializer):
    """Краткое представление сообщения, на которое отвечают."""

    sender_id = serializers.IntegerField(allow_null=True, read_only=True)
    text = serializers.SerializerMethodField()

    class Meta:
        model = Message
        fields = ("id", "sender_id", "text", "type")

    def get_text(self, obj) -> str:
        return "" if obj.deleted_at else obj.text


class MessageSerializer(serializers.ModelSerializer):
    """
    Сообщение в истории, событиях и списке чатов.

    Удалённое сообщение отдаётся с пустым текстом и без вложений (мягкое удаление).
    `call` заполняется в задаче 7.
    """

    channel_id = serializers.CharField(source="chat.channel_id", read_only=True)
    sender_id = serializers.IntegerField(allow_null=True, read_only=True)
    text = serializers.SerializerMethodField()
    reply_to = serializers.SerializerMethodField()
    attachments = serializers.SerializerMethodField()
    call = serializers.SerializerMethodField()

    class Meta:
        model = Message
        fields = (
            "id",
            "channel_id",
            "sender_id",
            "type",
            "custom_type",
            "text",
            "reply_to",
            "attachments",
            "call",
            "extra_data",
            "edited_at",
            "deleted_at",
            "created_at",
            "client_msg_id",
        )
        read_only_fields = fields

    def get_text(self, obj) -> str:
        return "" if obj.deleted_at else obj.text

    @extend_schema_field(ReplyToSerializer(allow_null=True))
    def get_reply_to(self, obj):
        if obj.reply_to_id is None or obj.reply_to is None:
            return None
        return ReplyToSerializer(obj.reply_to).data

    @extend_schema_field(AttachmentSerializer(many=True))
    def get_attachments(self, obj):
        if obj.deleted_at:
            return []
        # сортировка в Python, чтобы использовать prefetch_related("attachments") без N+1
        attachments = sorted(obj.attachments.all(), key=lambda attachment: (attachment.created_at, attachment.pk))
        return AttachmentSerializer(attachments, many=True).data

    @extend_schema_field(serializers.DictField(allow_null=True))
    def get_call(self, obj):
        # Task 7: данные звонка для type=call
        return None
