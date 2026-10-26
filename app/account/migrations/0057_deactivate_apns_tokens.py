from django.db import migrations

# Тот же шаблон, что в common.notifications.APNS_TOKEN_RE: миграции не
# импортируют код приложения, чтобы не зависеть от его будущих правок.
APNS_TOKEN_REGEX = r"^[0-9a-fA-F]{64}$"


def deactivate_apns_tokens(apps, schema_editor):
    """Гасит APNs-токены, которые старые iOS-сборки сохранили в /api/device/gcm/.

    FCM на них отвечает INVALID_ARGUMENT: каждая отправка тратилась впустую и
    записывалась ошибкой в статус пушей.
    """
    GCMDevice = apps.get_model("push_notifications", "GCMDevice")
    GCMDevice.objects.filter(
        active=True,
        registration_id__regex=APNS_TOKEN_REGEX,
    ).update(active=False)


class Migration(migrations.Migration):

    dependencies = [
        ('account', '0056_non_working_date'),
        ('push_notifications', '0011_alter_apnsdevice_registration_id'),
    ]

    operations = [
        migrations.RunPython(deactivate_apns_tokens, migrations.RunPython.noop),
    ]
