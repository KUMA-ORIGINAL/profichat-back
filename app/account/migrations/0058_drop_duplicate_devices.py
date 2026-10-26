from django.db import migrations
from django.db.models import Count, Max


def drop_duplicate_devices(apps, schema_editor):
    """Удаляет дубли GCMDevice с одним и тем же токеном, оставляя самый новый.

    Дубли создавали параллельные регистрации одного токена: из-за них
    register-fcm отвечал 500 (MultipleObjectsReturned), а пуш приходил на
    телефон по разу на каждую строку. Состояния доставки удаляются каскадом.
    """
    GCMDevice = apps.get_model("push_notifications", "GCMDevice")
    duplicated = (
        # order_by() без полей: сортировка по умолчанию попала бы в GROUP BY.
        GCMDevice.objects.order_by()
        .values("registration_id")
        .annotate(rows=Count("id"), newest=Max("id"))
        .filter(rows__gt=1)
    )
    for group in duplicated:
        GCMDevice.objects.filter(registration_id=group["registration_id"]).exclude(
            id=group["newest"],
        ).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('account', '0057_deactivate_apns_tokens'),
    ]

    operations = [
        migrations.RunPython(drop_duplicate_devices, migrations.RunPython.noop),
    ]
