# Generated by Django 5.1 on 2025-06-05 10:03

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('account', '0023_user_education_user_work_experience'),
    ]

    operations = [
        migrations.AlterField(
            model_name='user',
            name='education',
            field=models.CharField(blank=True, max_length=255, null=True, verbose_name='Образование'),
        ),
        migrations.AlterField(
            model_name='user',
            name='work_experience',
            field=models.CharField(blank=True, max_length=255, null=True, verbose_name='Опыт работы'),
        ),
    ]
