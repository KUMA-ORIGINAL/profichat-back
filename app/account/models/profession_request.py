from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _

from common.models import BaseModel


class ProfessionRequest(BaseModel):
    """Заявка на добавление профессии, которой нет в справочнике.

    Подаётся из двух мест: вместе с анкетой «Стать профессионалом»
    (``custom_profession`` + описание) и отдельно из «Редактировать профиль».
    Обе попадают в одну очередь модерации.
    """

    STATUS_PENDING = 'pending'
    STATUS_APPROVED = 'approved'
    STATUS_REJECTED = 'rejected'
    STATUS_CHOICES = (
        (STATUS_PENDING, 'На проверке'),
        (STATUS_APPROVED, 'Одобрена'),
        (STATUS_REJECTED, 'Отклонена'),
    )

    SOURCE_APPLICATION = 'application'
    SOURCE_PROFILE = 'profile'
    SOURCE_CHOICES = (
        (SOURCE_APPLICATION, 'Анкета специалиста'),
        (SOURCE_PROFILE, 'Профиль'),
    )

    NAME_MAX_LENGTH = 100
    DESCRIPTION_MAX_LENGTH = 500

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='profession_requests',
        verbose_name=_("Пользователь"),
    )
    # Из анкеты имя приходит в custom_profession (до 255), поэтому колонка шире лимита API.
    name = models.CharField(max_length=255, verbose_name=_("Название профессии"))
    description = models.TextField(blank=True, verbose_name=_("Краткое описание"))
    source = models.CharField(
        max_length=20,
        choices=SOURCE_CHOICES,
        default=SOURCE_PROFILE,
        verbose_name=_("Откуда подана"),
    )
    application = models.OneToOneField(
        'Application',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='profession_request',
        verbose_name=_("Анкета"),
    )
    status = models.CharField(
        max_length=10,
        choices=STATUS_CHOICES,
        default=STATUS_PENDING,
        db_index=True,
        verbose_name=_("Статус"),
    )
    reason = models.TextField(blank=True, verbose_name=_("Причина отказа"))
    profession_category = models.ForeignKey(
        'ProfessionCategory',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='profession_requests',
        verbose_name=_("Категория после одобрения"),
        help_text=_("Оставьте пустым — при одобрении категория будет создана по названию заявки."),
    )
    reviewed_at = models.DateTimeField(null=True, blank=True, verbose_name=_("Дата решения"))

    class Meta:
        verbose_name = _("Заявка на профессию")
        verbose_name_plural = _("Заявки на профессии")
        ordering = ('-created_at',)

    def __str__(self):
        return f"{self.name} ({self.get_status_display()})"
