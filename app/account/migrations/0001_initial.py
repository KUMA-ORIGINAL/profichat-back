# Generated by Django 5.1 on 2025-03-16 21:07

import django.contrib.auth.validators
import django.core.validators
import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ('auth', '0012_alter_user_first_name_max_length'),
    ]

    operations = [
        migrations.CreateModel(
            name='ProfessionCategory',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=255, verbose_name='Название')),
            ],
            options={
                'verbose_name': 'Категория специальности',
                'verbose_name_plural': 'Категории специальностей',
            },
        ),
        migrations.CreateModel(
            name='User',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('password', models.CharField(max_length=128, verbose_name='password')),
                ('last_login', models.DateTimeField(blank=True, null=True, verbose_name='last login')),
                ('is_superuser', models.BooleanField(default=False, help_text='Designates that this user has all permissions without explicitly assigning them.', verbose_name='superuser status')),
                ('username', models.CharField(error_messages={'unique': 'A user with that username already exists.'}, help_text='Required. 150 characters or fewer. Letters, digits and @/./+/-/_ only.', max_length=150, unique=True, validators=[django.contrib.auth.validators.UnicodeUsernameValidator()], verbose_name='username')),
                ('email', models.EmailField(blank=True, max_length=254, verbose_name='email address')),
                ('is_staff', models.BooleanField(default=False, help_text='Designates whether the user can log into this admin site.', verbose_name='staff status')),
                ('is_active', models.BooleanField(default=True, help_text='Designates whether this user should be treated as active. Unselect this instead of deleting accounts.', verbose_name='active')),
                ('date_joined', models.DateTimeField(default=django.utils.timezone.now, verbose_name='date joined')),
                ('first_name', models.CharField(max_length=255, verbose_name='Имя')),
                ('last_name', models.CharField(max_length=255, verbose_name='Фамилия')),
                ('gender', models.CharField(blank=True, choices=[('male', 'Мужской'), ('female', 'Женский'), ('other', 'Другой')], max_length=10, null=True, verbose_name='Пол')),
                ('birthdate', models.DateField(blank=True, null=True, verbose_name='Дата рождения')),
                ('description', models.TextField(blank=True, null=True, verbose_name='Описание')),
                ('phone_number', models.CharField(blank=True, max_length=15, validators=[django.core.validators.RegexValidator(message='Enter a valid phone number.', regex='^\\+?1?\\d{9,15}$')], verbose_name='phone number')),
                ('photo', models.ImageField(blank=True, null=True, upload_to='user/photos/%Y/%m/%d/', verbose_name='Фото')),
                ('role', models.CharField(blank=True, choices=[('accountant', 'Клиент'), ('doctor', 'Специалист')], max_length=20, verbose_name='Роль')),
                ('is_invited', models.BooleanField(default=False, verbose_name='Приглашен')),
                ('groups', models.ManyToManyField(blank=True, help_text='The groups this user belongs to. A user will get all permissions granted to each of their groups.', related_name='user_set', related_query_name='user', to='auth.group', verbose_name='groups')),
                ('inviter', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to=settings.AUTH_USER_MODEL, verbose_name='Реферал (кто пригласил)')),
                ('user_permissions', models.ManyToManyField(blank=True, help_text='Specific permissions for this user.', related_name='user_set', related_query_name='user', to='auth.permission', verbose_name='user permissions')),
                ('profession', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='users', to='account.professioncategory', verbose_name='Профессия')),
            ],
            options={
                'verbose_name': 'User',
                'verbose_name_plural': 'Users',
                'ordering': ('-date_joined',),
            },
        ),
    ]
