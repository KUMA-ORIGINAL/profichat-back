from datetime import timedelta

from django.contrib.auth import get_user_model

from account.models import ROLE_CLIENT
from common.errors import AppError
from messenger.services import access
from messenger.tests.base import MessengerTestCase

User = get_user_model()


class AccessTests(MessengerTestCase):
    def test_has_active_tariff(self):
        self.assertFalse(access.has_active_tariff(self.chat))
        order = self.activate_tariff(hours=2)
        self.assertTrue(access.has_active_tariff(self.chat))
        self.assertFalse(access.has_active_tariff(self.chat, now=order.expires_at + timedelta(seconds=1)))

    def test_client_without_tariff_cannot_send(self):
        with self.assertRaises(AppError) as ctx:
            access.ensure_can_send(self.chat, self.client_user)
        self.assertEqual(ctx.exception.error_code, "TARIFF_REQUIRED")
        self.assertEqual(ctx.exception.status_code, 403)

    def test_client_with_tariff_can_send(self):
        self.activate_tariff()
        access.ensure_can_send(self.chat, self.client_user)

    def test_specialist_without_tariff_can_send(self):
        access.ensure_can_send(self.chat, self.specialist)

    def test_specialist_without_tariff_cannot_call(self):
        with self.assertRaises(AppError) as ctx:
            access.ensure_can_call(self.chat, self.specialist)
        self.assertEqual(ctx.exception.error_code, "TARIFF_REQUIRED")
        self.assertEqual(ctx.exception.status_code, 403)

    def test_client_without_tariff_cannot_call(self):
        with self.assertRaises(AppError) as ctx:
            access.ensure_can_call(self.chat, self.client_user)
        self.assertEqual(ctx.exception.error_code, "TARIFF_REQUIRED")

    def test_can_call_with_tariff(self):
        self.activate_tariff()
        access.ensure_can_call(self.chat, self.specialist)
        access.ensure_can_call(self.chat, self.client_user)

    def test_client_voice_forbidden_when_disabled(self):
        self.activate_tariff()
        self.chat.client_can_send_voice = False
        self.chat.save()
        with self.assertRaises(AppError) as ctx:
            access.ensure_can_send_voice(self.chat, self.client_user)
        self.assertEqual(ctx.exception.error_code, "VOICE_NOT_ALLOWED")
        self.assertEqual(ctx.exception.status_code, 403)

    def test_specialist_voice_allowed_when_client_voice_disabled(self):
        self.chat.client_can_send_voice = False
        self.chat.save()
        access.ensure_can_send_voice(self.chat, self.specialist)

    def test_client_voice_requires_tariff(self):
        with self.assertRaises(AppError) as ctx:
            access.ensure_can_send_voice(self.chat, self.client_user)
        self.assertEqual(ctx.exception.error_code, "TARIFF_REQUIRED")

    def test_ensure_member(self):
        self.assertEqual(access.ensure_member(self.client_user, self.chat.channel_id), self.chat)
        self.assertEqual(access.ensure_member(self.specialist, self.chat.channel_id), self.chat)

    def test_ensure_member_rejects_stranger_and_unknown(self):
        stranger = User.objects.create_user(username="stranger", password="pass", role=ROLE_CLIENT)
        for user, channel in ((stranger, self.chat.channel_id), (self.client_user, "nope")):
            with self.assertRaises(AppError) as ctx:
                access.ensure_member(user, channel)
            self.assertEqual(ctx.exception.error_code, "CHAT_NOT_FOUND")
            self.assertEqual(ctx.exception.status_code, 404)
