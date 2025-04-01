# Generated by Django 5.1 on 2025-04-01 04:20

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('account', '0009_professioncategory_parent'),
    ]

    operations = [
        migrations.AlterModelOptions(
            name='application',
            options={'verbose_name': 'Заявка', 'verbose_name_plural': 'Заявки'},
        ),
        migrations.AlterModelOptions(
            name='workexperience',
            options={'verbose_name': 'Опыт работы', 'verbose_name_plural': 'Опыт работы'},
        ),
        migrations.RemoveField(
            model_name='application',
            name='profession',
        ),
        migrations.AddField(
            model_name='application',
            name='rejection_reason',
            field=models.TextField(blank=True, null=True, verbose_name='Причина отказа'),
        ),
        migrations.AddField(
            model_name='application',
            name='status',
            field=models.CharField(choices=[('pending', 'На рассмотрении'), ('accepted', 'Принято'), ('rejected', 'Отклонено')], default='pending', max_length=10, verbose_name='Статус заявки'),
        ),
        migrations.AddField(
            model_name='application',
            name='updated_at',
            field=models.DateTimeField(auto_now=True, verbose_name='Дата обновления'),
        ),
        migrations.AddField(
            model_name='application',
            name='user',
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.CASCADE, to=settings.AUTH_USER_MODEL, verbose_name='Пользователь'),
        ),
        migrations.AlterField(
            model_name='application',
            name='created_at',
            field=models.DateTimeField(auto_now_add=True, verbose_name='Дата создания'),
        ),
        migrations.AlterField(
            model_name='application',
            name='education',
            field=models.CharField(max_length=255, verbose_name='Образование'),
        ),
        migrations.AlterField(
            model_name='application',
            name='first_name',
            field=models.CharField(max_length=100, verbose_name='Имя'),
        ),
        migrations.AlterField(
            model_name='application',
            name='last_name',
            field=models.CharField(max_length=100, verbose_name='Фамилия'),
        ),
        migrations.AlterField(
            model_name='professioncategory',
            name='parent',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='subcategories', to='account.professioncategory', verbose_name='Родительская категория'),
        ),
        migrations.AlterField(
            model_name='workexperience',
            name='name',
            field=models.CharField(max_length=255, verbose_name='Место работы / описание опыта'),
        ),
    ]
