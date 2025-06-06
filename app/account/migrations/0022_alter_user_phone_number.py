# Generated by Django 5.1 on 2025-06-02 22:02

import phonenumber_field.modelfields
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('account', '0021_alter_user_phone_number'),
    ]

    operations = [
        migrations.AlterField(
            model_name='user',
            name='phone_number',
            field=phonenumber_field.modelfields.PhoneNumberField(max_length=128, region='KG', unique=True, verbose_name='phone number'),
        ),
    ]
