from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("integrations", "0001_sso_login_token"),
    ]

    operations = [
        migrations.CreateModel(
            name="ErkinAISyncState",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("feed", models.CharField(max_length=64, unique=True)),
                ("synced_at", models.DateTimeField(blank=True, null=True)),
                ("last_run_at", models.DateTimeField(blank=True, null=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "verbose_name": "Состояние синхронизации ErkinAI",
                "verbose_name_plural": "Состояния синхронизации ErkinAI",
            },
        ),
    ]
