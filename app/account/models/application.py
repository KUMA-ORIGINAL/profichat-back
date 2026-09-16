from django.db import models
from django.utils.translation import gettext_lazy as _


class Application(models.Model):
    STATUS_CHOICES = [
        ('pending', 'На рассмотрении'),
        ('accepted', 'Принято'),
        ('rejected', 'Отклонено'),
    ]

    first_name = models.CharField(max_length=100, verbose_name=_("Имя"))
    last_name = models.CharField(max_length=100, verbose_name=_("Фамилия"))
    status = models.CharField(
        max_length=10,
        choices=STATUS_CHOICES,
        default='pending',
        verbose_name=_("Статус заявки")
    )
    rejection_reason = models.TextField(
        blank=True,
        null=True,
        verbose_name=_("Причина отказа")
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name=_("Дата создания"))
    updated_at = models.DateTimeField(auto_now=True, verbose_name=_("Дата обновления"))
    profession = models.ForeignKey(
        to='ProfessionCategory',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="applications",
        verbose_name=_("Профессия"),
    )
    organization = models.ForeignKey(
        to='Organization',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="applications",
        verbose_name=_("Организация"),
    )
    custom_profession = models.CharField(
        max_length=255,
        null=True,
        blank=True,
        verbose_name=_("Профессия (свой вариант)")
    )
    custom_profession_description = models.CharField(
        max_length=500,
        blank=True,
        default='',
        verbose_name=_("Описание профессии (свой вариант)")
    )
    custom_organization = models.CharField(
        max_length=255,
        null=True,
        blank=True,
        verbose_name=_("Организация (свой вариант)")
    )
    user = models.ForeignKey(
        to='User',
        on_delete=models.CASCADE,
        null=True,
        verbose_name=_("Пользователь")
    )

    class Meta:
        verbose_name = _("Заявка")
        verbose_name_plural = _("Заявки")

    def __str__(self):
        profession_name = self.profession.name if self.profession else self.custom_profession
        return f"{self.last_name} {self.first_name} - {profession_name or 'Профессия не указана'}"


class WorkExperience(models.Model):
    application = models.ForeignKey(Application, related_name='work_experiences', on_delete=models.CASCADE)
    organization = models.CharField(max_length=255, verbose_name=_("Организация"))
    position = models.CharField(max_length=255, blank=True, verbose_name=_("Должность"))
    start_date = models.DateField(null=True, blank=True, verbose_name=_("Дата начала работы"))
    end_date = models.DateField(null=True, blank=True, verbose_name=_("Дата окончания работы"))
    is_current = models.BooleanField(default=False, verbose_name=_("Сейчас работает здесь"))

    class Meta:
        verbose_name = _("Опыт работы")
        verbose_name_plural = _("Опыт работы")

    def __str__(self):
        return f"{self.organization} — {self.position}" if self.position else self.organization


class ApplicationEducation(models.Model):
    application = models.ForeignKey(Application, related_name='educations', on_delete=models.CASCADE)
    institution = models.CharField(max_length=255, verbose_name=_("Учебное заведение"))
    faculty = models.CharField(max_length=255, blank=True, verbose_name=_("Факультет или направление"))
    start_date = models.DateField(null=True, blank=True, verbose_name=_("Дата начала обучения"))
    end_date = models.DateField(null=True, blank=True, verbose_name=_("Дата окончания обучения"))

    class Meta:
        verbose_name = _("Образование в заявке")
        verbose_name_plural = _("Образование в заявках")

    def __str__(self):
        return self.institution
