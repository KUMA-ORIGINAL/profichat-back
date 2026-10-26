from django.utils import timezone

from messenger.tests.base import MessengerTestCase


class MessengerTestCaseSmokeTests(MessengerTestCase):
    def test_setup_creates_chat(self):
        self.assertEqual(self.chat.client_id, self.client_user.id)
        self.assertEqual(self.chat.specialist_id, self.specialist.id)
        self.assertEqual(
            self.chat.channel_id, f"chat_{self.client_user.id}_{self.specialist.id}"
        )

    def test_activate_tariff_makes_active_order(self):
        order = self.activate_tariff(hours=24)
        self.assertTrue(order.is_active)
        self.assertTrue(
            self.chat.access_orders.filter(
                payment_status="success", expires_at__gt=timezone.now()
            ).exists()
        )

    def test_auth_sets_user(self):
        self.auth(self.client_user)
        response = self.client.get("/api/health/")
        self.assertEqual(response.status_code, 200)

    def test_broadcast_is_mocked(self):
        from messenger.clients import centrifugo

        centrifugo.broadcast(["personal:1"], {"x": 1})
        self.broadcast_mock.assert_called_once_with(["personal:1"], {"x": 1})

    def test_celery_runs_eagerly(self):
        from config.celery import app

        self.assertTrue(app.conf.task_always_eager)
