import logging

from django.contrib.auth.base_user import BaseUserManager
from django.db import models
from django.contrib.auth.models import AbstractUser
from django.utils.translation import gettext_lazy as _
from django.core.validators import RegexValidator
from phonenumber_field.modelfields import PhoneNumberField

from .work_schedule import WorkSchedule
from common.stream_client import chat_client

logger = logging.getLogger(__name__)


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

STREAM_SYNC_FIELDS = {
    "first_name",
    "last_name",
    "phone_number",
    "photo",
}

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

        # -----------------------------
        # Stream sync logic
        # -----------------------------

    def _get_stream_payload(self) -> dict:
        """Формирует payload для Stream"""
        data = {
            "id": str(self.id),
            "first_name": self.first_name,
            "last_name": self.last_name,
        }

        if self.phone_number:
            data["phone_number"] = str(self.phone_number)

        if self.photo:
            data["photo"] = self.photo.url

        return data

    def upsert_stream_user(self) -> None:
        """Создаёт или обновляет пользователя в Stream"""
        payload = self._get_stream_payload()

        try:
            chat_client.upsert_user(payload)
            logger.info("Stream user synced: %s", self.id)

        except Exception as e:
            message = str(e).lower()

            if "deleted" in message:
                self._recreate_stream_user(payload)
            else:
                logger.exception(
                    "Stream sync failed for user %s", self.id
                )

    def _recreate_stream_user(self, payload: dict) -> None:
        """Пересоздаёт пользователя, если он был удалён в Stream"""
        try:
            chat_client.create_user(payload)
            logger.info("Stream user recreated: %s", self.id)
        except Exception:
            logger.exception(
                "Failed to recreate Stream user %s", self.id
            )

    def delete_stream_user(self) -> None:
        """Удаляет пользователя из Stream"""
        try:
            chat_client.delete_user(str(self.id))
            logger.info("Stream user deleted: %s", self.id)
        except Exception:
            logger.exception(
                "Failed to delete Stream user %s", self.id
            )

        # -----------------------------
        # Django overrides
        # -----------------------------

    def save(self, *args, **kwargs):
        update_fields = kwargs.get("update_fields")

        super().save(*args, **kwargs)

        if not update_fields or STREAM_SYNC_FIELDS.intersection(update_fields):
            self.upsert_stream_user()

    def delete(self, using=None, keep_parents=False, hard=False):
        """
        hard=True  → полное удаление + удаление из Stream
        hard=False → soft delete (Stream не трогаем)
        """
        if hard:
            self.delete_stream_user()
            return super().delete(using=using, keep_parents=keep_parents)

        # soft delete
        self.is_active = False
        self.old_phone_number = self.phone_number
        self.phone_number = None

        self.save(update_fields=[
            "is_active",
            "phone_number",
            "old_phone_number",
        ])
