from django.db import transaction
from django.utils import timezone

from messenger.models import ChatMember
from messenger.services import events


def ensure_members(chat) -> None:
    """Гарантирует наличие двух ChatMember (клиент и специалист) у чата. Идемпотентно."""
    ChatMember.objects.get_or_create(
        chat=chat, user_id=chat.client_id, defaults={"role": ChatMember.Role.CLIENT}
    )
    ChatMember.objects.get_or_create(
        chat=chat, user_id=chat.specialist_id, defaults={"role": ChatMember.Role.SPECIALIST}
    )


def _locked_member(chat, user) -> ChatMember:
    ensure_members(chat)
    return ChatMember.objects.select_for_update().get(chat=chat, user_id=user.pk)


def pin_chat(chat, user) -> ChatMember:
    """
    Закрепить чат у себя (как membership.pinned_at в Stream). Идемпотентно: повторное закрепление
    сохраняет исходное время. `chat.updated` — только своим устройствам.
    """
    with transaction.atomic():
        member = _locked_member(chat, user)
        if member.pinned_at is None:
            member.pinned_at = timezone.now()
            member.save(update_fields=["pinned_at", "updated_at"])
        events.publish_chat_updated_to(chat, user)
    return member


def unpin_chat(chat, user) -> bool:
    """Открепить чат у себя. Возвращает, был ли он закреплён; `chat.updated` — только своим устройствам."""
    with transaction.atomic():
        member = _locked_member(chat, user)
        was_pinned = member.pinned_at is not None
        if was_pinned:
            member.pinned_at = None
            member.save(update_fields=["pinned_at", "updated_at"])
        events.publish_chat_updated_to(chat, user)
    return was_pinned
