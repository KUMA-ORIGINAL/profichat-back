from django.db.models import Exists, OuterRef, Q
from django.utils import timezone
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema, extend_schema_view
from rest_framework import mixins, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from account.services.stream import (
    hide_channel_for_user,
    mute_user_for_user,
    unmute_user_for_user,
)
from account.models import ROLE_SPECIALIST
from common.errors import AppError, ErrorCode
from messenger.models import ChatMember
from messenger.services.access import ensure_member
from messenger.services.events import format_datetime
from messenger.services.members import pin_chat, unpin_chat
from ..models import AccessOrder, BlockedChat, Chat, FavoriteChat
from ..serializers import (
    BlockedChatSerializer,
    ChatCreateSerializer,
    ChatListSerializer,
    ChatUpdateSerializer,
    FavoriteChatRequestSerializer,
    FavoriteChatSerializer,
    PinChatRequestSerializer,
    SoftDeleteChatRequestSerializer,
)
from ..services import (
    build_chat_list_item,
    apply_companion_presence,
    visible_chats,
    chat_list_queryset,
    create_or_get_chat,
    get_should_reply_map,
    sync_blocked_by_to_stream,
    sync_favorite_by_to_stream,
    update_chat_and_stream,
)


@extend_schema(tags=["Chats"])
@extend_schema_view(
    list=extend_schema(
        summary="Chat list",
        parameters=[
            OpenApiParameter(
                name="access_status",
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                required=False,
                enum=["active", "inactive"],
            )
        ],
    ),
    create=extend_schema(summary="Create chat"),
    retrieve=extend_schema(
        summary="Chat by channel_id",
        parameters=[
            OpenApiParameter(
                name="id",
                type=OpenApiTypes.STR,
                location=OpenApiParameter.PATH,
                description="channel_id чата",
            )
        ],
    ),
)
class ChatViewSet(
    viewsets.GenericViewSet,
    mixins.ListModelMixin,
    mixins.CreateModelMixin,
    mixins.UpdateModelMixin,
):
    queryset = Chat.objects.all()
    permission_classes = [IsAuthenticated]

    def get_serializer_class(self):
        if self.action == "create":
            return ChatCreateSerializer
        if self.action in ["update", "partial_update"]:
            return ChatUpdateSerializer
        return ChatListSerializer

    def update(self, request, *args, **kwargs):
        if request.user.role != ROLE_SPECIALIST:
            raise AppError("Only specialists can edit chat notes", code=ErrorCode.SPECIALIST_ONLY, status_code=403)
        return super().update(request, *args, **kwargs)

    def _ensure_specialist_for_favorites(self, user):
        if user.role != ROLE_SPECIALIST:
            raise AppError("Only specialists can manage favorites", code=ErrorCode.SPECIALIST_ONLY, status_code=403)

    def _ensure_specialist_for_blacklist(self, user):
        if user.role != ROLE_SPECIALIST:
            raise AppError("Only specialists can manage blacklist", code=ErrorCode.SPECIALIST_ONLY, status_code=403)

    def _resolve_member_chat(self, user, channel_id):
        return (
            Chat.objects.filter(channel_id=channel_id)
            .filter(Q(client=user) | Q(specialist=user))
            .first()
        )

    @staticmethod
    def _resolve_companion_user_id(chat, user):
        if chat.client_id == user.id:
            return chat.specialist_id
        return chat.client_id

    def list(self, request, *args, **kwargs):
        chats = list(self.get_queryset())
        should_reply_map = get_should_reply_map(chats, request.user)
        items = [build_chat_list_item(chat, request.user, should_reply_map, include_presence=True) for chat in chats]

        page = self.paginate_queryset(items)
        # «в сети» — только для отдаваемых чатов (страница, если есть пагинация)
        apply_companion_presence(page if page is not None else items, request.user)
        if page is not None:
            serializer = ChatListSerializer(page, many=True)
            return self.get_paginated_response(serializer.data)

        serializer = ChatListSerializer(items, many=True)
        return Response(serializer.data)

    def retrieve(self, request, pk=None):
        """Один чат по channel_id (в URL detail-маршрута) в формате списка; только для участника."""
        chat = ensure_member(request.user, pk)
        chat = chat_list_queryset(Chat.objects.filter(pk=chat.pk), request.user).get()
        item = build_chat_list_item(
            chat, request.user, get_should_reply_map([chat], request.user), include_presence=True
        )
        apply_companion_presence([item], request.user)
        return Response(ChatListSerializer(item).data)

    def perform_create(self, serializer):
        client = serializer.validated_data["client"]
        specialist = serializer.validated_data["specialist"]
        chat = create_or_get_chat(client=client, specialist=specialist)
        serializer.instance = chat

    def perform_update(self, serializer):
        update_chat_and_stream(serializer.instance, serializer.validated_data)

    @extend_schema(
        request=SoftDeleteChatRequestSerializer,
        summary="Soft delete chat",
        responses={200: OpenApiResponse(description="Chat soft deleted for current user")},
    )
    @action(detail=False, methods=["post"], url_path="soft-delete")
    def soft_delete(self, request):
        if request.user.role != ROLE_SPECIALIST:
            raise AppError("Only specialists can delete chats", code=ErrorCode.SPECIALIST_ONLY, status_code=403)

        serializer = SoftDeleteChatRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        channel_id = serializer.validated_data["channel_id"]
        chat = self._resolve_member_chat(request.user, channel_id)
        if not chat:
            raise AppError("Chat not found or unavailable", code=ErrorCode.CHAT_NOT_FOUND, status_code=404)

        now = timezone.now()
        update_fields = []
        if chat.deleted_by_specialist_at is None:
            chat.deleted_by_specialist_at = now
            update_fields.append("deleted_by_specialist_at")

        if update_fields:
            chat.save(update_fields=update_fields)
        hide_channel_for_user(chat.channel_id, request.user.id)
        return Response({"status": "success", "channel_id": channel_id})

    @extend_schema(
        summary="Get favorite chat channel ids",
        responses={200: OpenApiResponse(description="Favorite channel ids returned")},
    )
    @action(detail=False, methods=["get"], url_path="favorites")
    def favorites(self, request):
        self._ensure_specialist_for_favorites(request.user)
        favorite_channel_ids = list(
            FavoriteChat.objects.filter(user=request.user)
            .select_related("chat")
            .values_list("chat__channel_id", flat=True)
        )
        return Response({"channel_ids": favorite_channel_ids})

    @extend_schema(
        request=FavoriteChatRequestSerializer,
        summary="Add chat to favorites",
        responses={200: FavoriteChatSerializer},
    )
    @action(detail=False, methods=["post"], url_path="favorites/add")
    def add_favorite(self, request):
        self._ensure_specialist_for_favorites(request.user)
        serializer = FavoriteChatRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        channel_id = serializer.validated_data["channel_id"]
        chat = self._resolve_member_chat(request.user, channel_id)
        if not chat:
            raise AppError("Chat not found or unavailable", code=ErrorCode.CHAT_NOT_FOUND, status_code=404)

        favorite, _ = FavoriteChat.objects.get_or_create(user=request.user, chat=chat)
        sync_favorite_by_to_stream(chat)
        return Response(FavoriteChatSerializer(favorite).data)

    @extend_schema(
        request=FavoriteChatRequestSerializer,
        summary="Remove chat from favorites",
        responses={200: OpenApiResponse(description="Favorite removed")},
    )
    @action(detail=False, methods=["post"], url_path="favorites/remove")
    def remove_favorite(self, request):
        self._ensure_specialist_for_favorites(request.user)
        serializer = FavoriteChatRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        channel_id = serializer.validated_data["channel_id"]
        chat = self._resolve_member_chat(request.user, channel_id)
        if not chat:
            raise AppError("Chat not found or unavailable", code=ErrorCode.CHAT_NOT_FOUND, status_code=404)

        deleted, _ = FavoriteChat.objects.filter(user=request.user, chat=chat).delete()
        sync_favorite_by_to_stream(chat)
        return Response({"status": "success", "deleted": bool(deleted)})

    @extend_schema(
        request=PinChatRequestSerializer,
        summary="Pin chat (own list)",
        responses={200: OpenApiResponse(description="{channelId, pinnedAt}")},
    )
    @action(detail=False, methods=["post"], url_path="pins/add")
    def add_pin(self, request):
        serializer = PinChatRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        chat = ensure_member(request.user, serializer.validated_data["channel_id"])
        member = pin_chat(chat, request.user)
        return Response({"channel_id": chat.channel_id, "pinned_at": format_datetime(member.pinned_at)})

    @extend_schema(
        request=PinChatRequestSerializer,
        summary="Unpin chat (own list)",
        responses={200: OpenApiResponse(description="Pin removed")},
    )
    @action(detail=False, methods=["post"], url_path="pins/remove")
    def remove_pin(self, request):
        serializer = PinChatRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        chat = ensure_member(request.user, serializer.validated_data["channel_id"])
        deleted = unpin_chat(chat, request.user)
        return Response({"status": "success", "deleted": deleted})

    @extend_schema(summary="Get blacklisted chat channel ids")
    @action(detail=False, methods=["get"], url_path="blacklist")
    def blacklist(self, request):
        self._ensure_specialist_for_blacklist(request.user)
        blocked_channel_ids = list(
            BlockedChat.objects.filter(user=request.user)
            .select_related("chat")
            .values_list("chat__channel_id", flat=True)
        )
        return Response({"channel_ids": blocked_channel_ids})

    @extend_schema(
        request=FavoriteChatRequestSerializer,
        summary="Add chat to blacklist",
        responses={200: BlockedChatSerializer},
    )
    @action(detail=False, methods=["post"], url_path="blacklist/add")
    def add_blacklist(self, request):
        self._ensure_specialist_for_blacklist(request.user)
        serializer = FavoriteChatRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        channel_id = serializer.validated_data["channel_id"]
        chat = self._resolve_member_chat(request.user, channel_id)
        if not chat:
            raise AppError("Chat not found or unavailable", code=ErrorCode.CHAT_NOT_FOUND, status_code=404)

        blocked, _ = BlockedChat.objects.get_or_create(user=request.user, chat=chat)
        ChatMember.objects.filter(chat=chat, user=request.user).update(muted=True)
        sync_blocked_by_to_stream(chat)
        companion_user_id = self._resolve_companion_user_id(chat, request.user)
        mute_user_for_user(request.user.id, companion_user_id)
        return Response(BlockedChatSerializer(blocked).data)

    @extend_schema(
        request=FavoriteChatRequestSerializer,
        summary="Remove chat from blacklist",
    )
    @action(detail=False, methods=["post"], url_path="blacklist/remove")
    def remove_blacklist(self, request):
        self._ensure_specialist_for_blacklist(request.user)
        serializer = FavoriteChatRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        channel_id = serializer.validated_data["channel_id"]
        chat = self._resolve_member_chat(request.user, channel_id)
        if not chat:
            raise AppError("Chat not found or unavailable", code=ErrorCode.CHAT_NOT_FOUND, status_code=404)

        deleted, _ = BlockedChat.objects.filter(user=request.user, chat=chat).delete()
        ChatMember.objects.filter(chat=chat, user=request.user).update(muted=False)
        sync_blocked_by_to_stream(chat)
        companion_user_id = self._resolve_companion_user_id(chat, request.user)
        unmute_user_for_user(request.user.id, companion_user_id)
        return Response({"status": "success", "deleted": bool(deleted)})

    def get_queryset(self):
        user = self.request.user
        access_status = self.request.query_params.get("access_status")

        base_qs = visible_chats(user)

        if access_status in ("active", "inactive"):
            has_active_access = Exists(
                AccessOrder.objects.filter(
                    chat=OuterRef("pk"),
                    payment_status="success",
                    expires_at__gt=timezone.now(),
                )
            )
            base_qs = base_qs.filter(client=user)
            base_qs = base_qs.filter(has_active_access) if access_status == "active" else base_qs.exclude(
                has_active_access
            )

        if self.action == "list":
            return chat_list_queryset(base_qs, user)
        return base_qs
