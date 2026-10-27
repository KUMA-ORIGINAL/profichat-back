from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from messenger.models import Message
from messenger.serializers.attachment import AttachmentSerializer
from messenger.serializers.call import CallSerializer


def attachment_order_key(attachment) -> tuple:
    """Порядок вложений в сообщении: position (порядок attachmentIds), затем created_at, pk."""
    position = attachment.position if attachment.position is not None else 32767
    return position, attachment.created_at, str(attachment.pk)


class ReplyToAttachmentSerializer(AttachmentSerializer):
    """Краткое первое вложение сообщения, на которое отвечают (превью в цитате)."""

    class Meta(AttachmentSerializer.Meta):
        fields = ("id", "kind", "file_name", "url")
        read_only_fields = fields


class ReplyToSerializer(serializers.ModelSerializer):
    """
    Краткое представление сообщения, на которое отвечают.

    У удалённого — пустой текст и `attachment: null`. Без N+1 в выборках нужен
    prefetch_related("reply_to__attachments").
    """

    sender_id = serializers.IntegerField(allow_null=True, read_only=True)
    text = serializers.SerializerMethodField()
    attachment = serializers.SerializerMethodField()

    class Meta:
        model = Message
        fields = ("id", "sender_id", "text", "type", "created_at", "deleted_at", "attachment")

    def get_text(self, obj) -> str:
        return "" if obj.deleted_at else obj.text

    @extend_schema_field(ReplyToAttachmentSerializer(allow_null=True))
    def get_attachment(self, obj):
        if obj.deleted_at:
            return None
        attachments = obj.attachments.all()
        if not attachments:
            return None
        return ReplyToAttachmentSerializer(min(attachments, key=attachment_order_key)).data


class MessageSerializer(serializers.ModelSerializer):
    """
    Сообщение в истории, событиях и списке чатов.

    Удалённое сообщение отдаётся с пустым текстом и без вложений (мягкое удаление).
    `call` — звонок для `type=call` (иначе null); в выборках нужен select_related("call").
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
        # порядок отправки (attachmentIds); сортировка в Python — по prefetch_related("attachments") без N+1
        attachments = sorted(obj.attachments.all(), key=attachment_order_key)
        return AttachmentSerializer(attachments, many=True).data

    @extend_schema_field(CallSerializer(allow_null=True))
    def get_call(self, obj):
        if obj.call_id is None or obj.call is None:
            return None
        call = obj.call
        if call.chat_id == obj.chat_id:
            call.chat = obj.chat  # channel_id без лишнего запроса
        return CallSerializer(call).data
