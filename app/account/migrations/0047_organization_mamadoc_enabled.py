from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("account", "0046_add_socialnetwork_alter_sociallink"),
    ]

    operations = [
        migrations.AddField(
            model_name="organization",
            name="mamadoc_enabled",
            field=models.BooleanField(default=False, verbose_name="Подключена интеграция MamaDoc"),
        ),
    ]
