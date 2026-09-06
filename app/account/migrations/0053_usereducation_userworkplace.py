from django.db import migrations, models
import django.db.models.deletion


def migrate_legacy_profile_fields(apps, schema_editor):
    User = apps.get_model("account", "User")
    UserEducation = apps.get_model("account", "UserEducation")
    Application = apps.get_model("account", "Application")
    ApplicationEducation = apps.get_model("account", "ApplicationEducation")

    for user in User.objects.exclude(education__isnull=True).exclude(education="").iterator():
        UserEducation.objects.create(user_id=user.id, institution=user.education)

    for application in Application.objects.exclude(education="").iterator():
        ApplicationEducation.objects.create(
            application_id=application.id,
            institution=application.education,
        )


class Migration(migrations.Migration):

    dependencies = [
        ("account", "0052_erkinai_directory_link"),
    ]

    operations = [
        migrations.RenameField(
            model_name="workexperience",
            old_name="name",
            new_name="organization",
        ),
        migrations.AlterField(
            model_name="workexperience",
            name="organization",
            field=models.CharField(max_length=255, verbose_name="Организация"),
        ),
        migrations.AddField(
            model_name="workexperience",
            name="position",
            field=models.CharField(blank=True, max_length=255, verbose_name="Должность"),
        ),
        migrations.AddField(
            model_name="workexperience",
            name="start_date",
            field=models.DateField(blank=True, null=True, verbose_name="Дата начала работы"),
        ),
        migrations.AddField(
            model_name="workexperience",
            name="end_date",
            field=models.DateField(blank=True, null=True, verbose_name="Дата окончания работы"),
        ),
        migrations.AddField(
            model_name="workexperience",
            name="is_current",
            field=models.BooleanField(default=False, verbose_name="Сейчас работает здесь"),
        ),
        migrations.CreateModel(
            name="ApplicationEducation",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("institution", models.CharField(max_length=255, verbose_name="Учебное заведение")),
                ("faculty", models.CharField(blank=True, max_length=255, verbose_name="Факультет или направление")),
                ("start_date", models.DateField(blank=True, null=True, verbose_name="Дата начала обучения")),
                ("end_date", models.DateField(blank=True, null=True, verbose_name="Дата окончания обучения")),
                ("application", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="educations", to="account.application")),
            ],
            options={
                "verbose_name": "Образование в заявке",
                "verbose_name_plural": "Образование в заявках",
            },
        ),
        migrations.CreateModel(
            name="UserEducation",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("institution", models.CharField(max_length=255, verbose_name="Учебное заведение")),
                ("faculty", models.CharField(blank=True, max_length=255, verbose_name="Факультет или направление")),
                ("start_date", models.DateField(blank=True, null=True, verbose_name="Дата начала обучения")),
                ("end_date", models.DateField(blank=True, null=True, verbose_name="Дата окончания обучения")),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="educations", to="account.user", verbose_name="Пользователь")),
            ],
            options={
                "verbose_name": "Образование пользователя",
                "verbose_name_plural": "Образование пользователей",
                "ordering": ("-start_date", "-id"),
            },
        ),
        migrations.CreateModel(
            name="UserWorkplace",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("organization", models.CharField(max_length=255, verbose_name="Организация")),
                ("position", models.CharField(blank=True, max_length=255, verbose_name="Должность")),
                ("start_date", models.DateField(blank=True, null=True, verbose_name="Дата начала работы")),
                ("end_date", models.DateField(blank=True, null=True, verbose_name="Дата окончания работы")),
                ("is_current", models.BooleanField(default=False, verbose_name="Сейчас работает здесь")),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="workplaces", to="account.user", verbose_name="Пользователь")),
            ],
            options={
                "verbose_name": "Место работы пользователя",
                "verbose_name_plural": "Места работы пользователей",
                "ordering": ("-is_current", "-start_date", "-id"),
            },
        ),
        migrations.RunPython(migrate_legacy_profile_fields, migrations.RunPython.noop),
        migrations.RemoveField(
            model_name="application",
            name="education",
        ),
    ]
