from django.db.models.signals import post_delete
from django.dispatch import receiver
from .models import Chat
from account.services.stream import delete_stream_channel


@receiver(post_delete, sender=Chat)
def delete_stream_channel_on_chat_delete(sender, instance, **kwargs):
    delete_stream_channel(instance.channel_id)
