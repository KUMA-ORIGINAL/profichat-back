# Generated by Django 5.1 on 2025-04-07 17:30

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('account', '0011_application_profession'),
    ]

    operations = [
        migrations.AddField(
            model_name='user',
            name='show_in_search',
            field=models.BooleanField(default=True, verbose_name='Показывать в поиске'),
        ),
    ]
