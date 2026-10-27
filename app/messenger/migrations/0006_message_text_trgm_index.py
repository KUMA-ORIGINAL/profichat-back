import django.contrib.postgres.indexes
import django.db.models.functions.text
from django.contrib.postgres.operations import AddIndexConcurrently, TrigramExtension
from django.db import migrations, models


class Migration(migrations.Migration):
    # CREATE INDEX CONCURRENTLY нельзя внутри транзакции; запись в messenger_message не блокируется
    atomic = False

    dependencies = [
        ("messenger", "0005_chatmember_user_change_markers"),
    ]

    operations = [
        TrigramExtension(),
        AddIndexConcurrently(
            model_name="message",
            index=django.contrib.postgres.indexes.GinIndex(
                django.contrib.postgres.indexes.OpClass(
                    django.db.models.functions.text.Upper("text"), name="gin_trgm_ops"
                ),
                condition=models.Q(("deleted_at__isnull", True), ("type", "regular")),
                name="msg_text_upper_trgm_idx",
            ),
        ),
    ]
