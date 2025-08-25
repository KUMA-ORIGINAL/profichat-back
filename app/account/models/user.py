import logging

from django.contrib.auth.base_user import BaseUserManager
from django.db import models
from django.contrib.auth.models import AbstractUser
from django.utils.translation import gettext_lazy as _
from django.core.validators import RegexValidator
from phonenumber_field.modelfields import PhoneNumberField

from account.models import WorkSchedule
from common.stream_client import chat_client


class UserManager(BaseUserManager):

    def create_user(self, username=None, phone_number=None, first_name=None, last_name=None, is_active=True, password=None, **extra_fields):
        if not username:
            # генерируем username если не передан
            import uuid
            username = f"user_{uuid.uuid4().hex[:10]}"

        user = self.model(
            phone_number=phone_number,
            username=username,
            first_name=first_name,
            last_name=last_name,
            is_active=is_active,
            **extra_fields
        )
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self,username=None, password=None, **extra_fields):
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
        extra_fields.setdefault('is_active', True)
        return self.create_user(
            username=username,
            password=password,
            **extra_fields
        )



ROLE_CLIENT = 'client'
ROLE_SPECIALIST = 'specialist'

class User(AbstractUser):
    ROLE_CHOICES = (
        (ROLE_CLIENT, "Клиент"),
        (ROLE_SPECIALIST, "Специалист"),
    )
    GENDER_CHOICES = (
        ("male", _("Мужской")),
        ("female", _("Женский")),
        ("other", _("Другой"))
    )

    first_name = models.CharField(
        max_length=255,
        verbose_name='Имя',
        blank=True,
        null=True,
    )
    last_name = models.CharField(
        max_length=255,
        verbose_name='Фамилия',
        blank=True,
        null=True,
    )
    gender = models.CharField(_("Пол"), max_length=10, choices=GENDER_CHOICES, blank=True, null=True)
    birthdate = models.DateField(_("Дата рождения"), blank=True, null=True)
    description = models.TextField(_("Описание"), blank=True, null=True)
    balance = models.DecimalField(_("Баланс"), max_digits=12, decimal_places=2, default=0)
    phone_number = PhoneNumberField(_("phone number"), unique=False, region='KG', null=True)
    old_phone_number = PhoneNumberField(_("Старый номер телефона"), unique=False, region='KG', null=True, blank=True)
    photo = models.ImageField(
        upload_to='user/photos/%Y/%m/%d/',
        blank=True,
        null=True,
        verbose_name='Фото'
    )
    role = models.CharField(
        max_length=20,
        choices=ROLE_CHOICES,
        default=ROLE_CLIENT,
        blank=True,
        verbose_name='Роль'
    )
    profession = models.ForeignKey(
        'ProfessionCategory',
        verbose_name=_("Профессия"),
        on_delete=models.SET_NULL, null=True, blank=True,
        related_name="users"
    )
    education = models.CharField("Образование", max_length=255, blank=True, null=True)
    work_experience = models.CharField("Опыт работы", max_length=255, blank=True, null=True)
    inviter = models.ForeignKey("self", verbose_name=_("Реферал (кто пригласил)"), on_delete=models.SET_NULL, null=True,
                                blank=True)
    is_invited = models.BooleanField(_("Приглашен"), default=False)
    is_active = models.BooleanField(
        _("active"),
        default=True,
        help_text=_(
            "Designates whether this user should be treated as active. "
            "Unselect this instead of deleting accounts."
        ),
    )
    show_in_search = models.BooleanField(default=True, verbose_name="Показывать в поиске")
    invite_greeting = models.TextField(
        blank=True,
        null=True,
        verbose_name="Приветственный текст для приглашения"
    )
    can_audio_call = models.BooleanField(
        _("Можно ли звонить пользователю (АУДИО)"),
        default=True
    )
    can_video_call = models.BooleanField(
        _("Можно ли звонить пользователю (ВИДЕО)"),
        default=True
    )

    USERNAME_FIELD = "username"
    REQUIRED_FIELDS = []  # Required fields when creating a superuser

    objects = UserManager()

    class Meta:
        ordering = ('-date_joined',)
        verbose_name = "User"
        verbose_name_plural = "Users"

    def __str__(self):
        return f"{self.first_name} {self.last_name}"

    def get_work_schedule_data(self):
        """Собираем расписание пользователя для sync с GetStream"""
        schedules = WorkSchedule.objects.filter(user_id=self.id)
        return [
            {
                "id": ws.id,
                "dayOfWeek": ws.day_of_week,
                "fromTime": ws.from_time.isoformat(),
                "toTime": ws.to_time.isoformat(),
            }
            for ws in schedules
        ]

    def upsert_stream_user(self) -> None:
        """Создаёт/обновляет пользователя в Stream вместе с расписанием"""
        try:
            chat_client.upsert_user({
                "id": str(self.id),
                "phone_number": str(self.phone_number),
                "first_name": self.first_name,
                "last_name": self.last_name,
                "photo": self.photo.url if self.photo else None,
                "can_audio_call": self.can_audio_call,
                "can_video_call": self.can_video_call,
                "work_schedule": self.get_work_schedule_data(),  # <-- ВАЖНО
            })
        except Exception as e:
            error_message = str(e)
            if "was deleted" in error_message:
                try:
                    chat_client.create_user({
                        "id": str(self.id),
                        "phone_number": str(self.phone_number),
                        "first_name": self.first_name,
                        "last_name": self.last_name,
                        "photo": self.photo.url if self.photo else None,
                        "can_audio_call": self.can_audio_call,
                        "can_video_call": self.can_video_call,
                        "work_schedule": self.get_work_schedule_data(),
                    })
                    logging.info("Пользователь %s был пересоздан в GetStream.", self.id)
                except Exception as ex:
                    logging.error("Ошибка при создании удалённого пользователя в GetStream: %s", ex)
            else:
                logging.error("Ошибка при синхронизации пользователя с GetStream: %s", e)

    def delete_stream_user(self):
        try:
            chat_client.delete_user(str(self.id))
        except Exception as e:
            logging.error("Ошибка при удалении пользователя из GetStream: %s", e)

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        # Автоматическая синхронизация в GetStream при любом изменении
        self.upsert_stream_user()

    def delete(self, using=None, keep_parents=False, hard=False):
        self.delete_stream_user()
        if hard:
            return super().delete(using=using, keep_parents=keep_parents)
        self.is_active = False
        self.old_phone_number = self.phone_number
        self.phone_number = None
        self.save(update_fields=['is_active', 'phone_number', 'old_phone_number'])
