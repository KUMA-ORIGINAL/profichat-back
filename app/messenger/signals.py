from django.db.models.signals import post_save
from django.dispatch import receiver

from chat_access.models import Chat


@receiver(post_save, sender=Chat, dispatch_uid="messenger_chat_ensure_members")
def create_members_for_new_chat(sender, instance, created, raw=False, **kwargs):
    """Инвариант «по 2 ChatMember на чат» на любом пути создания чата."""
    if created and not raw:
        from messenger.services import ensure_members

        ensure_members(instance)
