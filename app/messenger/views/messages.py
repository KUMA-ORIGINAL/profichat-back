from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema, inline_serializer
from rest_framework import serializers, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from common.errors import AppError, ErrorCode
from messenger.models import Message
from messenger.serializers import MessageSerializer
from messenger.services import access, messages as message_service, read_state


class SendMessageRequestSerializer(serializers.Serializer):
    client_msg_id = serializers.UUIDField(required=False, allow_null=True)
    text = serializers.CharField(required=False, allow_blank=True, default="", trim_whitespace=False, max_length=10000)
    reply_to_id = serializers.IntegerField(required=False, allow_null=True)
    attachment_ids = serializers.ListField(child=serializers.UUIDField(), required=False, default=list)


class EditMessageRequestSerializer(serializers.Serializer):
    text = serializers.CharField(allow_blank=True, trim_whitespace=False, max_length=10000)


class MarkReadRequestSerializer(serializers.Serializer):
    last_read_message_id = serializers.IntegerField()


HistoryResponseSerializer = inline_serializer(
    name="MessageHistory",
    fields={
        "results": MessageSerializer(many=True),
        "has_more": serializers.BooleanField(),
        "next_cursor": serializers.CharField(allow_null=True),
    },
)

ReadResponseSerializer = inline_serializer(
    name="ChatReadState",
    fields={
        "channel_id": serializers.CharField(),
        "last_read_message_id": serializers.IntegerField(allow_null=True),
        "unread_count": serializers.IntegerField(),
    },
)


def _parse_limit(raw) -> int:
    if raw in (None, ""):
        return message_service.DEFAULT_LIMIT
    try:
        limit = int(raw)
    except (TypeError, ValueError):
        limit = 0
    if limit < 1:
        raise AppError("Некорректный limit", code=ErrorCode.PARAM_INVALID, status_code=400)
    return min(limit, message_service.MAX_LIMIT)


@extend_schema(tags=["Messenger"])
class ChatMessagesView(APIView):
    """История сообщений чата и отправка сообщения."""

    permission_classes = [IsAuthenticated]

    @extend_schema(
        summary="Message history",
        parameters=[
            OpenApiParameter("before", OpenApiTypes.STR, OpenApiParameter.QUERY, required=False),
            OpenApiParameter("after", OpenApiTypes.STR, OpenApiParameter.QUERY, required=False),
            OpenApiParameter("limit", OpenApiTypes.INT, OpenApiParameter.QUERY, required=False),
        ],
        responses=HistoryResponseSerializer,
    )
    def get(self, request, channel_id):
        chat = access.ensure_member(request.user, channel_id)
        limit = _parse_limit(request.query_params.get("limit"))
        items, has_more, next_cursor = message_service.list_messages(
            chat,
            before=request.query_params.get("before") or None,
            after=request.query_params.get("after") or None,
            limit=limit,
        )
        return Response(
            {
                "results": MessageSerializer(items, many=True).data,
                "has_more": has_more,
                "next_cursor": next_cursor,
            }
        )

    @extend_schema(
        summary="Send message",
        request=SendMessageRequestSerializer,
        responses={201: MessageSerializer},
    )
    def post(self, request, channel_id):
        chat = access.ensure_member(request.user, channel_id)
        serializer = SendMessageRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        # Повтор с тем же clientMsgId возвращает уже созданное сообщение, даже если тариф успел истечь
        client_msg_id = data.get("client_msg_id")
        if client_msg_id is not None:
            existing = message_service.find_by_client_msg_id(chat, request.user, client_msg_id)
            if existing is not None:
                return Response(MessageSerializer(existing).data, status=status.HTTP_201_CREATED)

        access.ensure_can_send(chat, request.user)
        message = message_service.send_message(
            chat,
            request.user,
            text=data.get("text") or "",
            client_msg_id=client_msg_id,
            reply_to_id=data.get("reply_to_id"),
            attachment_ids=data.get("attachment_ids") or [],
        )
        return Response(MessageSerializer(message).data, status=status.HTTP_201_CREATED)


@extend_schema(tags=["Messenger"])
class ChatMessageDetailView(APIView):
    """Редактирование и мягкое удаление своего сообщения (без проверки тарифа)."""

    permission_classes = [IsAuthenticated]

    def _get_message(self, request, channel_id, pk):
        chat = access.ensure_member(request.user, channel_id)
        message = Message.objects.select_related("reply_to", "call").filter(chat=chat, pk=pk).first()
        if message is None:
            raise AppError("Сообщение не найдено", code=ErrorCode.MESSAGE_NOT_FOUND, status_code=404)
        message.chat = chat
        return message

    @extend_schema(summary="Edit message", request=EditMessageRequestSerializer, responses=MessageSerializer)
    def patch(self, request, channel_id, pk):
        message = self._get_message(request, channel_id, pk)
        serializer = EditMessageRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        message = message_service.edit_message(message, request.user, serializer.validated_data["text"])
        return Response(MessageSerializer(message).data)

    @extend_schema(summary="Delete message", request=None, responses=MessageSerializer)
    def delete(self, request, channel_id, pk):
        message = self._get_message(request, channel_id, pk)
        message = message_service.delete_message(message, request.user)
        return Response(MessageSerializer(message).data)


@extend_schema(tags=["Messenger"])
class ChatReadView(APIView):
    """Отметка «прочитано» (без проверки тарифа)."""

    permission_classes = [IsAuthenticated]

    @extend_schema(summary="Mark chat read", request=MarkReadRequestSerializer, responses=ReadResponseSerializer)
    def post(self, request, channel_id):
        chat = access.ensure_member(request.user, channel_id)
        serializer = MarkReadRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        member = read_state.mark_read(chat, request.user, serializer.validated_data["last_read_message_id"])
        return Response(
            {
                "channel_id": chat.channel_id,
                "last_read_message_id": member.last_read_message_id,
                "unread_count": member.unread_count,
            }
        )
