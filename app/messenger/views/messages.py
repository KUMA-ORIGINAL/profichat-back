from django.conf import settings
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema, inline_serializer
from rest_framework import serializers, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from common.errors import AppError, ErrorCode
from messenger.models import Message
from messenger.serializers import MessageSerializer
from messenger.services import access, messages as message_service, presence, read_state


class SendMessageRequestSerializer(serializers.Serializer):
    client_msg_id = serializers.UUIDField(required=False, allow_null=True)
    text = serializers.CharField(required=False, allow_blank=True, default="", trim_whitespace=False, max_length=10000)
    reply_to_id = serializers.IntegerField(required=False, allow_null=True)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # attachment_ids: лимит MESSENGER_MAX_ATTACHMENTS_PER_MESSAGE читается при создании сериализатора,
        # а не при импорте модуля (так его видит и override_settings)
        self.fields["attachment_ids"] = serializers.ListField(
            child=serializers.UUIDField(),
            required=False,
            default=list,
            max_length=settings.MESSENGER_MAX_ATTACHMENTS_PER_MESSAGE,
        )


class EditMessageRequestSerializer(serializers.Serializer):
    text = serializers.CharField(allow_blank=True, trim_whitespace=False, max_length=10000)


class MarkReadRequestSerializer(serializers.Serializer):
    last_read_message_id = serializers.IntegerField()


class MarkUnreadRequestSerializer(serializers.Serializer):
    message_id = serializers.IntegerField()


HistoryResponseSerializer = inline_serializer(
    name="MessageHistory",
    fields={
        "results": MessageSerializer(many=True),
        "has_more": serializers.BooleanField(),
        "next_cursor": serializers.CharField(allow_null=True),
    },
)

HistoryAroundResponseSerializer = inline_serializer(
    name="MessageHistoryAround",
    fields={
        "results": MessageSerializer(many=True),
        "has_more_before": serializers.BooleanField(),
        "has_more_after": serializers.BooleanField(),
        "before_cursor": serializers.CharField(),
        "after_cursor": serializers.CharField(),
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


def _parse_limit(raw, default=message_service.DEFAULT_LIMIT, maximum=message_service.MAX_LIMIT) -> int:
    if raw in (None, ""):
        return default
    try:
        limit = int(raw)
    except (TypeError, ValueError):
        limit = 0
    if limit < 1:
        raise AppError("Некорректный limit", code=ErrorCode.PARAM_INVALID, status_code=400)
    return min(limit, maximum)


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
            OpenApiParameter(
                "around", OpenApiTypes.INT, OpenApiParameter.QUERY, required=False,
                description="id сообщения: окно вокруг него (ответ — MessageHistoryAround)",
            ),
        ],
        responses=HistoryResponseSerializer,
    )
    def get(self, request, channel_id):
        chat = access.ensure_member(request.user, channel_id)
        limit = _parse_limit(request.query_params.get("limit"))
        around = request.query_params.get("around")
        if around not in (None, ""):
            return self._around(request, chat, around, limit)
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

    @staticmethod
    def _around(request, chat, around, limit):
        if request.query_params.get("before") or request.query_params.get("after"):
            raise AppError(
                "around нельзя передавать вместе с before/after", code=ErrorCode.PARAM_INVALID, status_code=400
            )
        try:
            message_id = int(around)
        except (TypeError, ValueError):
            raise AppError("Некорректный around", code=ErrorCode.PARAM_INVALID, status_code=400)
        window = message_service.list_messages_around(chat, message_id, limit=limit)
        window["results"] = MessageSerializer(window["results"], many=True).data
        return Response(window)

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
        presence.touch(request.user.pk)
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
        presence.touch(request.user.pk)
        return Response(
            {
                "channel_id": chat.channel_id,
                "last_read_message_id": member.last_read_message_id,
                "unread_count": member.unread_count,
            }
        )


@extend_schema(tags=["Messenger"])
class ChatUnreadView(APIView):
    """«Пометить непрочитанным» с указанного сообщения (без проверки тарифа)."""

    permission_classes = [IsAuthenticated]

    @extend_schema(summary="Mark chat unread", request=MarkUnreadRequestSerializer, responses=ReadResponseSerializer)
    def post(self, request, channel_id):
        chat = access.ensure_member(request.user, channel_id)
        serializer = MarkUnreadRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        member = read_state.mark_unread(chat, request.user, serializer.validated_data["message_id"])
        presence.touch(request.user.pk)
        return Response(
            {
                "channel_id": chat.channel_id,
                "last_read_message_id": member.last_read_message_id,
                "unread_count": member.unread_count,
            }
        )


@extend_schema(tags=["Messenger"])
class MessageSearchView(APIView):
    """Поиск по тексту сообщений во всех своих (не скрытых) чатах."""

    permission_classes = [IsAuthenticated]

    @extend_schema(
        summary="Search messages",
        parameters=[
            OpenApiParameter("q", OpenApiTypes.STR, OpenApiParameter.QUERY, required=True),
            OpenApiParameter("before", OpenApiTypes.STR, OpenApiParameter.QUERY, required=False),
            OpenApiParameter("limit", OpenApiTypes.INT, OpenApiParameter.QUERY, required=False),
        ],
        responses=HistoryResponseSerializer,
    )
    def get(self, request):
        query = (request.query_params.get("q") or "").strip()
        min_length, max_length = message_service.SEARCH_MIN_QUERY_LENGTH, message_service.SEARCH_MAX_QUERY_LENGTH
        if not min_length <= len(query) <= max_length:
            raise AppError(
                f"Длина запроса — от {min_length} до {max_length} символов",
                code=ErrorCode.VALIDATION_ERROR,
                status_code=400,
            )
        limit = _parse_limit(
            request.query_params.get("limit"),
            default=message_service.SEARCH_DEFAULT_LIMIT,
            maximum=message_service.SEARCH_MAX_LIMIT,
        )
        items, has_more, next_cursor = message_service.search_messages(
            request.user, query, before=request.query_params.get("before") or None, limit=limit
        )
        return Response(
            {
                "results": MessageSerializer(items, many=True).data,
                "has_more": has_more,
                "next_cursor": next_cursor,
            }
        )
