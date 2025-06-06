# Generated by Django 5.1 on 2025-05-18 12:26

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('chat_access', '0003_alter_accessorder_duration_hours_and_more'),
    ]

    operations = [
        migrations.AlterField(
            model_name='accessorder',
            name='payment_status',
            field=models.CharField(choices=[('pending', 'Ожидает оплаты'), ('success', 'Успешно'), ('cancelled', 'Отменён')], default='pending', max_length=20, verbose_name='Статус оплаты'),
        ),
    ]
