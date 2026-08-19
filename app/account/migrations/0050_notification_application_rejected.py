from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("account", "0049_pushdevicestatus"),
    ]

    operations = [
        migrations.AlterField(
            model_name="notification",
            name="notification_type",
            field=models.CharField(
                choices=[
                    ("system", "Системное"),
                    ("payment_success", "Успешная оплата"),
                    ("chat_invite", "Приглашение в чат"),
                    ("application_accepted", "Заявка одобрена"),
                    ("application_rejected", "Заявка отклонена"),
                ],
                db_index=True,
                default="system",
                max_length=50,
                verbose_name="Тип уведомления",
            ),
        ),
    ]
