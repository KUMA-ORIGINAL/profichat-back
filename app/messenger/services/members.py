from messenger.models import ChatMember


def ensure_members(chat) -> None:
    """Гарантирует наличие двух ChatMember (клиент и специалист) у чата. Идемпотентно."""
    ChatMember.objects.get_or_create(
        chat=chat, user_id=chat.client_id, defaults={"role": ChatMember.Role.CLIENT}
    )
    ChatMember.objects.get_or_create(
        chat=chat, user_id=chat.specialist_id, defaults={"role": ChatMember.Role.SPECIALIST}
    )
