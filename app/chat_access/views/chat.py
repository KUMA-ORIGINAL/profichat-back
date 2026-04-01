from django.db.models import Prefetch, Q
from django.utils import timezone
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema, extend_schema_view
from rest_framework import exceptions, mixins, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from account.models import InviteDelivery, ROLE_CLIENT, ROLE_SPECIALIST
from ..models import AccessOrder, BlockedChat, Chat, FavoriteChat
from ..serializers import (
    BlockedChatSerializer,
    ChatCreateSerializer,
    ChatListSerializer,
    ChatUpdateSerializer,
    FavoriteChatRequestSerializer,
    FavoriteChatSerializer,
    SoftDeleteChatRequestSerializer,
)
from ..services import (
    build_chat_list_item,
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
            raise exceptions.PermissionDenied("Only specialists can edit chat notes")
        return super().update(request, *args, **kwargs)

    def _ensure_specialist_for_favorites(self, user):
        if user.role != ROLE_SPECIALIST:
            raise exceptions.PermissionDenied("Only specialists can manage favorites")

    def _ensure_specialist_for_blacklist(self, user):
        if user.role != ROLE_SPECIALIST:
            raise exceptions.PermissionDenied("Only specialists can manage blacklist")

    def _resolve_member_chat(self, user, channel_id):
        return (
            Chat.objects.filter(channel_id=channel_id)
            .filter(Q(client=user) | Q(specialist=user))
            .first()
        )

    def list(self, request, *args, **kwargs):
        chats = list(self.get_queryset())
        should_reply_map = get_should_reply_map(chats, request.user)
        items = [build_chat_list_item(chat, request.user, should_reply_map) for chat in chats]

        page = self.paginate_queryset(items)
        if page is not None:
            serializer = ChatListSerializer(page, many=True)
            return self.get_paginated_response(serializer.data)

        serializer = ChatListSerializer(items, many=True)
        return Response(serializer.data)

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
            raise exceptions.PermissionDenied("Only specialists can delete chats")

        serializer = SoftDeleteChatRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        channel_id = serializer.validated_data["channel_id"]
        chat = self._resolve_member_chat(request.user, channel_id)
        if not chat:
            raise exceptions.NotFound("Chat not found or unavailable")

        now = timezone.now()
        update_fields = []
        if chat.deleted_by_specialist_at is None:
            chat.deleted_by_specialist_at = now
            update_fields.append("deleted_by_specialist_at")

        if update_fields:
            chat.save(update_fields=update_fields)
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
            raise exceptions.NotFound("Chat not found or unavailable")

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
            raise exceptions.NotFound("Chat not found or unavailable")

        deleted, _ = FavoriteChat.objects.filter(user=request.user, chat=chat).delete()
        sync_favorite_by_to_stream(chat)
        return Response({"status": "success", "deleted": bool(deleted)})

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
            raise exceptions.NotFound("Chat not found or unavailable")

        blocked, _ = BlockedChat.objects.get_or_create(user=request.user, chat=chat)
        sync_blocked_by_to_stream(chat)
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
            raise exceptions.NotFound("Chat not found or unavailable")

        deleted, _ = BlockedChat.objects.filter(user=request.user, chat=chat).delete()
        sync_blocked_by_to_stream(chat)
        return Response({"status": "success", "deleted": bool(deleted)})

    def get_queryset(self):
        user = self.request.user
        access_status = self.request.query_params.get("access_status")

        if user.role == ROLE_SPECIALIST:
            base_qs = Chat.objects.filter(
                specialist=user,
                deleted_by_specialist_at__isnull=True,
            )
        elif user.role == ROLE_CLIENT:
            base_qs = Chat.objects.filter(
                client=user,
                deleted_by_client_at__isnull=True,
            )
        else:
            base_qs = Chat.objects.none()

        if access_status == "active":
            return base_qs.filter(
                client=user,
                access_orders__payment_status="success",
                access_orders__expires_at__gt=timezone.now(),
            ).distinct()

        if access_status == "inactive":
            return base_qs.filter(client=user).exclude(
                access_orders__payment_status="success",
                access_orders__expires_at__gt=timezone.now(),
            ).distinct()

        now = timezone.now()
        return base_qs.select_related("client", "specialist").prefetch_related(
            Prefetch(
                "invite_deliveries",
                queryset=InviteDelivery.objects.order_by("-created_at"),
                to_attr="prefetched_invite_deliveries",
            ),
            Prefetch(
                "access_orders",
                queryset=AccessOrder.objects.filter(
                    payment_status="success",
                    expires_at__gt=now,
                ).order_by("-created_at"),
                to_attr="prefetched_active_access_orders",
            ),
        )
