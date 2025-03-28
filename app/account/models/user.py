from django.contrib.auth.base_user import BaseUserManager
from django.db import models
from django.contrib.auth.models import AbstractUser
from django.utils.translation import gettext_lazy as _
from django.core.validators import RegexValidator

from ..stream_client import chat_client

class UserManager(BaseUserManager):

    def create_user(self, phone_number, password=None):
        """
        Создаёт пользователя с номером телефона и паролем.
        """
        if not phone_number:
            raise ValueError("У пользователя должен быть номер телефона")

        user = self.model(phone_number=phone_number)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, phone_number, password):
        """
        Создаёт суперпользователя.
        """
        user = self.create_user(phone_number, password)
        user.is_admin = True
        user.is_staff = True
        user.is_superuser = True
        user.save(using=self._db)
        return user


ROLE_CLIENT = 'client'  # Роль бухгалтера
ROLE_SPECIALIST = 'specialist'  # Роль врача

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
        verbose_name='Имя'
    )
    last_name = models.CharField(
        max_length=255,
        verbose_name='Фамилия'
    )
    gender = models.CharField(_("Пол"), max_length=10, choices=GENDER_CHOICES, blank=True, null=True)
    birthdate = models.DateField(_("Дата рождения"), blank=True, null=True)
    description = models.TextField(_("Описание"), blank=True, null=True)
    phone_number = models.CharField(
        _("phone number"),
        max_length=15,
        validators=[
            RegexValidator(regex=r'^\+?1?\d{9,15}$', message=_("Enter a valid phone number."))],
        unique=True,
    )
    photo = models.ImageField(
        upload_to='user/photos/%Y/%m/%d/',
        blank=True,
        null=True,
        verbose_name='Фото'
    )
    role = models.CharField(
        max_length=20,
        choices=ROLE_CHOICES,
        blank=True,
        verbose_name='Роль'
    )
    profession = models.ForeignKey(
        'ProfessionCategory',
        verbose_name=_("Профессия"),
        on_delete=models.SET_NULL, null=True, blank=True,
        related_name="users"
    )
    inviter = models.ForeignKey("self", verbose_name=_("Реферал (кто пригласил)"), on_delete=models.SET_NULL, null=True,
                                blank=True)
    is_invited = models.BooleanField(_("Приглашен"), default=False)
    is_active = models.BooleanField(default=True)

    username = None
    USERNAME_FIELD = "phone_number"
    REQUIRED_FIELDS = []  # Required fields when creating a superuser

    objects = UserManager()

    class Meta:
        ordering = ('-date_joined',)
        verbose_name = "User"
        verbose_name_plural = "Users"

    def __str__(self):
        return f"{self.first_name} {self.last_name}"

    def create_stream_user(self):
        """Создаёт пользователя в GetStream API"""
        chat_client.upsert_user({
            "id": str(self.id),
            "phone_number": self.phone_number,
            "first_name": self.first_name,
            "last_name": self.last_name,
            "photo": self.photo.url if self.photo else None,
        })
