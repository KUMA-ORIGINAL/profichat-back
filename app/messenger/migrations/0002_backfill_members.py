from django.db import migrations


def backfill(apps, schema_editor):
    """Создаёт ChatMember (клиент и специалист) для всех существующих чатов. Идемпотентно."""
    Chat = apps.get_model("chat_access", "Chat")
    ChatMember = apps.get_model("messenger", "ChatMember")

    batch = []
    for chat in Chat.objects.all().only("id", "client_id", "specialist_id").iterator(chunk_size=1000):
        batch.append(ChatMember(chat_id=chat.id, user_id=chat.client_id, role="client"))
        batch.append(ChatMember(chat_id=chat.id, user_id=chat.specialist_id, role="specialist"))
        if len(batch) >= 2000:
            ChatMember.objects.bulk_create(batch, ignore_conflicts=True)
            batch = []
    if batch:
        ChatMember.objects.bulk_create(batch, ignore_conflicts=True)


class Migration(migrations.Migration):

    dependencies = [
        ("messenger", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(backfill, migrations.RunPython.noop),
    ]
