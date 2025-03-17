# Generated by Django 5.1 on 2025-03-16 22:36

import django.core.validators
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('account', '0002_alter_user_managers_professioncategory_photo_and_more'),
    ]

    operations = [
        migrations.AlterModelManagers(
            name='user',
            managers=[
            ],
        ),
        migrations.AlterField(
            model_name='user',
            name='is_active',
            field=models.BooleanField(default=True),
        ),
        migrations.AlterField(
            model_name='user',
            name='phone_number',
            field=models.CharField(max_length=15, unique=True, validators=[django.core.validators.RegexValidator(message='Enter a valid phone number.', regex='^\\+?1?\\d{9,15}$')], verbose_name='phone number'),
        ),
    ]
