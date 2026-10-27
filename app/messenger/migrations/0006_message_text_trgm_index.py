import django.contrib.postgres.indexes
import django.db.models.functions.text
from django.contrib.postgres.operations import AddIndexConcurrently, BtreeGinExtension, TrigramExtension
from django.db import migrations, models

INDEX_NAME = "msg_chat_text_upper_trgm_idx"


class Migration(migrations.Migration):
    """
    Поиск по сообщениям: составной GIN-индекс (chat_id, UPPER(text) gin_trgm_ops) по обычным
    неудалённым сообщениям. chat_id (btree_gin) сужает поиск чатами пользователя, pg_trgm
    ускоряет ILIKE/UPPER LIKE '%q%'.

    CREATE INDEX CONCURRENTLY не блокирует запись, но не работает в транзакции (atomic = False)
    и ждёт завершения всех открытых транзакций. Если прошлый запуск прервался, остаётся
    INVALID-индекс с тем же именем — его удаляем перед созданием (MESSENGER_MIGRATION.md).
    """

    atomic = False

    dependencies = [
        ("messenger", "0005_chatmember_user_change_markers"),
    ]

    operations = [
        TrigramExtension(),
        BtreeGinExtension(),
        migrations.RunSQL(
            sql=f"DROP INDEX CONCURRENTLY IF EXISTS {INDEX_NAME}",
            reverse_sql=migrations.RunSQL.noop,
        ),
        AddIndexConcurrently(
            model_name="message",
            index=django.contrib.postgres.indexes.GinIndex(
                models.F("chat"),
                django.contrib.postgres.indexes.OpClass(
                    django.db.models.functions.text.Upper("text"), name="gin_trgm_ops"
                ),
                condition=models.Q(("deleted_at__isnull", True), ("type", "regular")),
                name=INDEX_NAME,
            ),
        ),
    ]
