from rest_framework import serializers

from messenger.clients import storage
from messenger.models import Attachment

DOWNLOAD_URL_TTL = 3600


class AttachmentSerializer(serializers.ModelSerializer):
    """Вложение в сообщении: метаданные и presigned GET-ссылка на час."""

    url = serializers.SerializerMethodField()

    class Meta:
        model = Attachment
        fields = (
            "id",
            "kind",
            "file_name",
            "mime_type",
            "size",
            "width",
            "height",
            "duration_ms",
            "waveform",
            "url",
        )
        read_only_fields = fields

    def get_url(self, obj) -> str:
        return storage.presigned_get(obj.object_key, DOWNLOAD_URL_TTL, obj.file_name)
