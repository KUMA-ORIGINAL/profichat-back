from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("chat_access", "0011_blockedchat"),
    ]

    operations = [
        migrations.AddField(
            model_name="chat",
            name="deleted_by_client_at",
            field=models.DateTimeField(blank=True, db_index=True, null=True),
        ),
        migrations.AddField(
            model_name="chat",
            name="deleted_by_specialist_at",
            field=models.DateTimeField(blank=True, db_index=True, null=True),
        ),
    ]
