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
    education = models.CharField(max_length=255, verbose_name=_("Образование"))
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
        return f"{self.last_name} {self.first_name} - {self.profession}"


class WorkExperience(models.Model):
    application = models.ForeignKey(Application, related_name='work_experiences', on_delete=models.CASCADE)
    name = models.CharField(max_length=255, verbose_name=_("Место работы / описание опыта"))

    class Meta:
        verbose_name = _("Опыт работы")
        verbose_name_plural = _("Опыт работы")

    def __str__(self):
        return f"{self.name}"
