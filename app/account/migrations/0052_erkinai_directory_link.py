from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("account", "0051_notification_erkinai"),
    ]

    operations = [
        migrations.AddField(
            model_name="organization",
            name="erkinai_id",
            field=models.PositiveIntegerField(
                blank=True,
                help_text=(
                    "Заполняется синхронизацией справочника. Организации с этим полем "
                    "приезжают из ErkinAI и перезаписываются при каждом запуске; "
                    "созданные вручную остаются пустыми и синхронизацией не трогаются."
                ),
                null=True,
                unique=True,
                verbose_name="ID в ErkinAI",
            ),
        ),
        migrations.AddField(
            model_name="organizationaddress",
            name="erkinai_branch_id",
            field=models.PositiveIntegerField(
                blank=True,
                help_text=(
                    "Адреса, приехавшие из филиалов ErkinAI. Без этого поля "
                    "синхронизация плодила бы дубликаты при каждом запуске."
                ),
                null=True,
                unique=True,
                verbose_name="ID филиала в ErkinAI",
            ),
        ),
    ]
