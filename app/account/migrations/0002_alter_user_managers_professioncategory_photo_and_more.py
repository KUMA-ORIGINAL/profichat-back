# Generated by Django 5.1 on 2025-03-16 21:20

import django.contrib.auth.models
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('account', '0001_initial'),
    ]

    operations = [
        migrations.AlterModelManagers(
            name='user',
            managers=[
                ('objects', django.contrib.auth.models.UserManager()),
            ],
        ),
        migrations.AddField(
            model_name='professioncategory',
            name='photo',
            field=models.ImageField(blank=True, null=True, upload_to='profession_categories/', verbose_name='Фото'),
        ),
        migrations.AlterField(
            model_name='professioncategory',
            name='name',
            field=models.CharField(max_length=255, verbose_name='Название категории'),
        ),
    ]
