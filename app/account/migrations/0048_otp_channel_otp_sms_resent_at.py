from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('account', '0047_organization_mamadoc_enabled'),
    ]

    operations = [
        migrations.AddField(
            model_name='otp',
            name='channel',
            field=models.CharField(
                choices=[('whatsapp', 'WhatsApp'), ('sms', 'SMS')],
                default='whatsapp',
                max_length=16,
                verbose_name='канал последней отправки',
            ),
        ),
        migrations.AddField(
            model_name='otp',
            name='sms_resent_at',
            field=models.DateTimeField(blank=True, null=True, verbose_name='повторно отправлен по SMS'),
        ),
    ]
