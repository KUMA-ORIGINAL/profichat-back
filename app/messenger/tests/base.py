from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APITestCase

from account.models import ROLE_CLIENT, ROLE_SPECIALIST
from chat_access.models import AccessOrder, Tariff
from chat_access.services.chat_commands import create_or_get_chat
from config.celery import app as celery_app

User = get_user_model()


@override_settings(CELERY_TASK_ALWAYS_EAGER=True)
class MessengerTestCase(APITestCase):
    """
    Общая база тестов мессенджера.

    - Celery выполняет задачи синхронно: CELERY_TASK_ALWAYS_EAGER=True (override_settings) и явно в конфигурации
      приложения Celery. Исключения задач не пробрасываются (task_eager_propagates=False), как в проде.
    - Сеть выключена: GetStream (upsert пользователя, создание канала) и Centrifugo замоканы.
      Публикации в Centrifugo доступны как `self.broadcast_mock`.
    """

    def setUp(self):
        super().setUp()
        # override_settings не доходит до уже загруженной конфигурации Celery — ставим явно
        previous = celery_app.conf.task_always_eager
        celery_app.conf.task_always_eager = True
        self.addCleanup(setattr, celery_app.conf, "task_always_eager", previous)

        for target in (
            "account.models.User.upsert_stream_user",
            "chat_access.services.chat_commands.create_stream_channel",
        ):
            patcher = patch(target)
            patcher.start()
            self.addCleanup(patcher.stop)

        broadcast_patcher = patch("messenger.clients.centrifugo.broadcast")
        self.broadcast_mock = broadcast_patcher.start()
        self.addCleanup(broadcast_patcher.stop)

        self.client_user = User.objects.create_user(
            username="client_1", password="pass", role=ROLE_CLIENT,
        )
        self.specialist = User.objects.create_user(
            username="specialist_1", password="pass", role=ROLE_SPECIALIST,
        )
        self.chat = create_or_get_chat(self.client_user, self.specialist)

    def auth(self, user):
        """Авторизует тестовый клиент от имени user."""
        self.client.force_authenticate(user=user)
        return user

    def activate_tariff(self, hours=24):
        """Создаёт оплаченный заказ доступа, активный на `hours` часов от текущего момента."""
        now = timezone.now()
        tariff = Tariff.objects.create(
            name="Тестовый тариф",
            price=0,
            duration_hours=hours,
            is_active=True,
            specialist=self.specialist,
        )
        return AccessOrder.objects.create(
            tariff=tariff,
            client=self.client_user,
            specialist=self.specialist,
            chat=self.chat,
            duration_hours=hours,
            tariff_type=tariff.tariff_type,
            price=tariff.price,
            payment_status="success",
            activated_at=now,
            expires_at=now + timedelta(hours=hours),
        )
