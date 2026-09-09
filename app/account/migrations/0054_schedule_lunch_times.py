from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('account', '0053_usereducation_userworkplace'),
    ]

    operations = [
        migrations.AddField(
            model_name='organizationworkschedule',
            name='lunch_from_time',
            field=models.TimeField(blank=True, null=True, verbose_name='Начало обеда'),
        ),
        migrations.AddField(
            model_name='organizationworkschedule',
            name='lunch_to_time',
            field=models.TimeField(blank=True, null=True, verbose_name='Окончание обеда'),
        ),
        migrations.AddField(
            model_name='workschedule',
            name='lunch_from_time',
            field=models.TimeField(blank=True, null=True, verbose_name='Начало обеда'),
        ),
        migrations.AddField(
            model_name='workschedule',
            name='lunch_to_time',
            field=models.TimeField(blank=True, null=True, verbose_name='Окончание обеда'),
        ),
    ]
