from drf_spectacular.utils import extend_schema, inline_serializer
from rest_framework import serializers, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from messenger.models import Attachment
from messenger.services import access, attachments as attachment_service


class CreateAttachmentRequestSerializer(serializers.Serializer):
    kind = serializers.ChoiceField(choices=Attachment.Kind.choices)
    file_name = serializers.CharField(max_length=255)
    mime_type = serializers.CharField(max_length=127)
    size = serializers.IntegerField(min_value=1)
    width = serializers.IntegerField(required=False, allow_null=True, min_value=0)
    height = serializers.IntegerField(required=False, allow_null=True, min_value=0)
    duration_ms = serializers.IntegerField(required=False, allow_null=True, min_value=0)
    waveform = serializers.ListField(
        child=serializers.IntegerField(), required=False, allow_null=True, max_length=512
    )


UploadResponseSerializer = inline_serializer(
    name="AttachmentUpload",
    fields={
        "id": serializers.UUIDField(),
        "upload_url": serializers.URLField(),
        "upload_headers": serializers.DictField(child=serializers.CharField()),
        "expires_at": serializers.DateTimeField(),
    },
)


@extend_schema(tags=["Messenger"])
class ChatAttachmentUploadView(APIView):
    """Резервирование вложения и presigned PUT-ссылка для загрузки файла напрямую в хранилище."""

    permission_classes = [IsAuthenticated]

    @extend_schema(
        summary="Create attachment upload",
        request=CreateAttachmentRequestSerializer,
        responses={201: UploadResponseSerializer},
    )
    def post(self, request, channel_id):
        chat = access.ensure_member(request.user, channel_id)
        serializer = CreateAttachmentRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        attachment, upload_url, expires_at = attachment_service.create_upload(
            chat, request.user, **serializer.validated_data
        )
        return Response(
            {
                "id": attachment.pk,
                "upload_url": upload_url,
                "upload_headers": {"Content-Type": attachment.mime_type},
                "expires_at": expires_at,
            },
            status=status.HTTP_201_CREATED,
        )
