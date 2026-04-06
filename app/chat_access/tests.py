from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from account.models import ROLE_CLIENT, ROLE_SPECIALIST
from account.models import InviteDelivery
from chat_access.models import AccessOrder, BlockedChat, Chat, FavoriteChat, Tariff

User = get_user_model()


class ChatBaseTestCase(APITestCase):
    def setUp(self):
        self.client_user = User.objects.create_user(
            username="client_1",
            password="pass",
            role=ROLE_CLIENT,
        )
        self.specialist_user = User.objects.create_user(
            username="specialist_1",
            password="pass",
            role=ROLE_SPECIALIST,
        )
        self.chat = Chat.objects.create(
            client=self.client_user,
            specialist=self.specialist_user,
            channel_id="chat_client_1_specialist_1",
        )

    def _mock_channels(self, sender_id=None, message_type="regular"):
        if sender_id is None:
            return {"channels": []}
        return {
            "channels": [
                {
                    "channel": {"id": self.chat.channel_id},
                    "messages": [
                        {
                            "type": message_type,
                            "user": {"id": str(sender_id)},
                            "text": "message",
                        }
                    ],
                }
            ]
        }


class ChatListTests(ChatBaseTestCase):
    def setUp(self):
        super().setUp()
        self.second_specialist = User.objects.create_user(
            username="specialist_2",
            password="pass",
            role=ROLE_SPECIALIST,
        )
        self.second_chat = Chat.objects.create(
            client=self.client_user,
            specialist=self.second_specialist,
            channel_id="chat_client_1_specialist_2",
        )

    @patch("chat_access.services.chat_list.chat_client")
    def test_requires_authentication(self, chat_client_mock):
        chat_client_mock.query_channels.return_value = {"channels": []}
        response = self.client.get(reverse("chat-list"))
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    @patch("chat_access.services.chat_list.chat_client")
    def test_client_list_shows_only_own_chats(self, chat_client_mock):
        outsider = User.objects.create_user(username="client_2", password="pass", role=ROLE_CLIENT)
        Chat.objects.create(
            client=outsider,
            specialist=self.specialist_user,
            channel_id="chat_client_2_specialist_1",
        )
        chat_client_mock.query_channels.return_value = {"channels": []}

        self.client.force_authenticate(user=self.client_user)
        response = self.client.get(reverse("chat-list"))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 2)
        self.assertEqual({item["user_role"] for item in response.data}, {"client"})

    @patch("chat_access.services.chat_list.chat_client")
    def test_specialist_note_visible_only_for_specialist(self, chat_client_mock):
        self.chat.specialist_note = "Private note"
        self.chat.save(update_fields=["specialist_note"])
        chat_client_mock.query_channels.return_value = {"channels": []}

        self.client.force_authenticate(user=self.client_user)
        client_response = self.client.get(reverse("chat-list"))
        self.assertIsNone(client_response.data[0]["specialist_note"])

        self.client.force_authenticate(user=self.specialist_user)
        specialist_response = self.client.get(reverse("chat-list"))
        self.assertEqual(specialist_response.data[0]["specialist_note"], "Private note")

    @patch("chat_access.services.chat_list.chat_client")
    def test_latest_invite_delivery_visible_only_for_specialist(self, chat_client_mock):
        InviteDelivery.objects.create(
            specialist=self.specialist_user,
            client=self.client_user,
            chat=self.chat,
            channel=InviteDelivery.CHANNEL_PUSH,
            status=InviteDelivery.STATUS_SENT,
        )
        chat_client_mock.query_channels.return_value = {"channels": []}

        self.client.force_authenticate(user=self.client_user)
        client_response = self.client.get(reverse("chat-list"))
        self.assertIsNone(client_response.data[0]["latest_invite_delivery"])

        self.client.force_authenticate(user=self.specialist_user)
        specialist_response = self.client.get(reverse("chat-list"))
        self.assertIsNotNone(specialist_response.data[0]["latest_invite_delivery"])
        self.assertEqual(
            specialist_response.data[0]["latest_invite_delivery"]["status"],
            InviteDelivery.STATUS_SENT,
        )

    @patch("chat_access.services.chat_list.chat_client")
    def test_access_status_filters_for_client(self, chat_client_mock):
        tariff = Tariff.objects.create(
            name="T1",
            price=100,
            duration_hours=24,
            specialist=self.specialist_user,
        )
        now = timezone.now()
        AccessOrder.objects.create(
            client=self.client_user,
            specialist=self.specialist_user,
            chat=self.chat,
            tariff=tariff,
            payment_status="success",
            activated_at=now - timedelta(hours=1),
            expires_at=now + timedelta(hours=1),
        )
        AccessOrder.objects.create(
            client=self.client_user,
            specialist=self.second_specialist,
            chat=self.second_chat,
            tariff=tariff,
            payment_status="success",
            activated_at=now - timedelta(days=2),
            expires_at=now - timedelta(days=1),
        )
        chat_client_mock.query_channels.return_value = {"channels": []}

        self.client.force_authenticate(user=self.client_user)
        active_response = self.client.get(reverse("chat-list"), {"access_status": "active"})
        inactive_response = self.client.get(reverse("chat-list"), {"access_status": "inactive"})

        self.assertEqual(len(active_response.data), 1)
        self.assertEqual(active_response.data[0]["channel_id"], self.chat.channel_id)
        self.assertEqual(len(inactive_response.data), 1)
        self.assertEqual(inactive_response.data[0]["channel_id"], self.second_chat.channel_id)


class ChatShouldReplyTests(ChatBaseTestCase):

    @patch("chat_access.services.chat_list.chat_client")
    def test_should_reply_true_when_last_message_from_companion(self, chat_client_mock):
        chat_client_mock.query_channels.return_value = self._mock_channels(sender_id=self.specialist_user.id)

        self.client.force_authenticate(user=self.client_user)
        response = self.client.get(reverse("chat-list"))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)
        self.assertTrue(response.data[0]["should_reply"])

    @patch("chat_access.services.chat_list.chat_client")
    def test_should_reply_false_when_last_message_from_current_user(self, chat_client_mock):
        chat_client_mock.query_channels.return_value = self._mock_channels(sender_id=self.client_user.id)

        self.client.force_authenticate(user=self.client_user)
        response = self.client.get(reverse("chat-list"))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)
        self.assertFalse(response.data[0]["should_reply"])

    @patch("chat_access.services.chat_list.chat_client")
    def test_should_reply_false_for_system_message(self, chat_client_mock):
        chat_client_mock.query_channels.return_value = self._mock_channels(
            sender_id=self.specialist_user.id,
            message_type="system",
        )

        self.client.force_authenticate(user=self.client_user)
        response = self.client.get(reverse("chat-list"))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(response.data[0]["should_reply"])

    @patch("chat_access.services.chat_list.chat_client")
    def test_should_reply_false_when_stream_fails(self, chat_client_mock):
        chat_client_mock.query_channels.side_effect = RuntimeError("stream down")

        self.client.force_authenticate(user=self.client_user)
        response = self.client.get(reverse("chat-list"))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(response.data[0]["should_reply"])


class ChatCommandTests(ChatBaseTestCase):
    @patch("chat_access.services.chat_commands.create_stream_channel")
    def test_create_chat_is_idempotent(self, create_stream_channel_mock):
        self.client.force_authenticate(user=self.client_user)

        first_response = self.client.post(
            reverse("chat-list"),
            data={"specialist": self.specialist_user.id},
            format="json",
        )
        second_response = self.client.post(
            reverse("chat-list"),
            data={"specialist": self.specialist_user.id},
            format="json",
        )

        self.assertEqual(first_response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(second_response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(Chat.objects.filter(client=self.client_user, specialist=self.specialist_user).count(), 1)
        create_stream_channel_mock.assert_not_called()

    @patch("chat_access.services.chat_commands.create_stream_channel")
    def test_create_chat_creates_stream_channel_for_new_chat(self, create_stream_channel_mock):
        new_specialist = User.objects.create_user(
            username="specialist_new",
            password="pass",
            role=ROLE_SPECIALIST,
        )
        self.client.force_authenticate(user=self.client_user)

        response = self.client.post(
            reverse("chat-list"),
            data={"specialist": new_specialist.id},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(Chat.objects.filter(client=self.client_user, specialist=new_specialist).count(), 1)
        create_stream_channel_mock.assert_called_once()

    @patch("chat_access.services.chat_commands.update_channel_extra_data")
    def test_specialist_can_update_chat(self, update_channel_extra_data_mock):
        self.client.force_authenticate(user=self.specialist_user)
        response = self.client.patch(
            reverse("chat-detail", kwargs={"pk": self.chat.id}),
            data={"specialist_note": "Updated note"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.chat.refresh_from_db()
        self.assertEqual(self.chat.specialist_note, "Updated note")
        update_channel_extra_data_mock.assert_called_once()

    def test_client_cannot_update_chat(self):
        self.client.force_authenticate(user=self.client_user)
        response = self.client.patch(
            reverse("chat-detail", kwargs={"pk": self.chat.id}),
            data={"specialist_note": "Try update"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)


class FavoriteChatTests(ChatBaseTestCase):
    def setUp(self):
        super().setUp()
        self.outsider = User.objects.create_user(
            username="client_outsider",
            password="pass",
            role=ROLE_CLIENT,
        )
        self.outsider_specialist = User.objects.create_user(
            username="specialist_outsider",
            password="pass",
            role=ROLE_SPECIALIST,
        )

    @patch("chat_access.views.chat.sync_favorite_by_to_stream")
    def test_specialist_can_add_favorite_by_channel_id(self, sync_mock):
        self.client.force_authenticate(user=self.specialist_user)
        response = self.client.post(
            reverse("chat-add-favorite"),
            data={"channel_id": self.chat.channel_id},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["channel_id"], self.chat.channel_id)
        self.assertTrue(FavoriteChat.objects.filter(user=self.specialist_user, chat=self.chat).exists())
        sync_mock.assert_called_once_with(self.chat)

    @patch("chat_access.views.chat.sync_favorite_by_to_stream")
    def test_specialist_add_favorite_is_idempotent(self, sync_mock):
        FavoriteChat.objects.create(user=self.specialist_user, chat=self.chat)
        self.client.force_authenticate(user=self.specialist_user)

        response = self.client.post(
            reverse("chat-add-favorite"),
            data={"channel_id": self.chat.channel_id},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(FavoriteChat.objects.filter(user=self.specialist_user, chat=self.chat).count(), 1)
        sync_mock.assert_called_once_with(self.chat)

    def test_add_favorite_denies_non_specialist(self):
        self.client.force_authenticate(user=self.outsider)
        response = self.client.post(
            reverse("chat-add-favorite"),
            data={"channel_id": self.chat.channel_id},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_specialist_can_list_favorite_channel_ids(self):
        FavoriteChat.objects.create(user=self.specialist_user, chat=self.chat)
        self.client.force_authenticate(user=self.specialist_user)

        response = self.client.get(reverse("chat-favorites"))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["channel_ids"], [self.chat.channel_id])

    @patch("chat_access.views.chat.sync_favorite_by_to_stream")
    def test_specialist_can_remove_favorite(self, sync_mock):
        FavoriteChat.objects.create(user=self.specialist_user, chat=self.chat)
        self.client.force_authenticate(user=self.specialist_user)

        response = self.client.post(
            reverse("chat-remove-favorite"),
            data={"channel_id": self.chat.channel_id},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["status"], "success")
        self.assertTrue(response.data["deleted"])
        self.assertFalse(FavoriteChat.objects.filter(user=self.specialist_user, chat=self.chat).exists())
        sync_mock.assert_called_once_with(self.chat)

    def test_remove_favorite_denies_non_member_specialist(self):
        self.client.force_authenticate(user=self.outsider_specialist)
        response = self.client.post(
            reverse("chat-remove-favorite"),
            data={"channel_id": self.chat.channel_id},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_client_cannot_list_favorites(self):
        self.client.force_authenticate(user=self.client_user)
        response = self.client.get(reverse("chat-favorites"))
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)


class BlacklistChatTests(ChatBaseTestCase):
    def setUp(self):
        super().setUp()
        self.outsider_specialist = User.objects.create_user(
            username="specialist_outsider_for_blacklist",
            password="pass",
            role=ROLE_SPECIALIST,
        )

    @patch("chat_access.views.chat.sync_blocked_by_to_stream")
    def test_specialist_can_add_chat_to_blacklist(self, sync_mock):
        self.client.force_authenticate(user=self.specialist_user)
        response = self.client.post(
            reverse("chat-add-blacklist"),
            data={"channel_id": self.chat.channel_id},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["channel_id"], self.chat.channel_id)
        self.assertTrue(BlockedChat.objects.filter(user=self.specialist_user, chat=self.chat).exists())
        sync_mock.assert_called_once_with(self.chat)

    @patch("chat_access.views.chat.sync_blocked_by_to_stream")
    def test_specialist_can_remove_chat_from_blacklist(self, sync_mock):
        BlockedChat.objects.create(user=self.specialist_user, chat=self.chat)
        self.client.force_authenticate(user=self.specialist_user)
        response = self.client.post(
            reverse("chat-remove-blacklist"),
            data={"channel_id": self.chat.channel_id},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["status"], "success")
        self.assertTrue(response.data["deleted"])
        self.assertFalse(BlockedChat.objects.filter(user=self.specialist_user, chat=self.chat).exists())
        sync_mock.assert_called_once_with(self.chat)

    def test_specialist_can_list_blacklist(self):
        BlockedChat.objects.create(user=self.specialist_user, chat=self.chat)
        self.client.force_authenticate(user=self.specialist_user)
        response = self.client.get(reverse("chat-blacklist"))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["channel_ids"], [self.chat.channel_id])

    def test_client_cannot_manage_blacklist(self):
        self.client.force_authenticate(user=self.client_user)
        add_response = self.client.post(
            reverse("chat-add-blacklist"),
            data={"channel_id": self.chat.channel_id},
            format="json",
        )
        list_response = self.client.get(reverse("chat-blacklist"))

        self.assertEqual(add_response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(list_response.status_code, status.HTTP_403_FORBIDDEN)

    def test_non_member_specialist_cannot_remove_blacklist(self):
        self.client.force_authenticate(user=self.outsider_specialist)
        response = self.client.post(
            reverse("chat-remove-blacklist"),
            data={"channel_id": self.chat.channel_id},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)


class ChatSoftDeleteTests(ChatBaseTestCase):
    @patch("chat_access.services.chat_list.chat_client")
    def test_client_cannot_soft_delete_chat(self, chat_client_mock):
        chat_client_mock.query_channels.return_value = {"channels": []}

        self.client.force_authenticate(user=self.client_user)
        delete_response = self.client.post(
            reverse("chat-soft-delete"),
            data={"channel_id": self.chat.channel_id},
            format="json",
        )
        self.assertEqual(delete_response.status_code, status.HTTP_403_FORBIDDEN)

    @patch("chat_access.services.chat_list.chat_client")
    def test_specialist_soft_delete_hides_chat_only_for_specialist(self, chat_client_mock):
        chat_client_mock.query_channels.return_value = {"channels": []}

        self.client.force_authenticate(user=self.specialist_user)
        delete_response = self.client.post(
            reverse("chat-soft-delete"),
            data={"channel_id": self.chat.channel_id},
            format="json",
        )
        self.assertEqual(delete_response.status_code, status.HTTP_200_OK)

        specialist_list_response = self.client.get(reverse("chat-list"))
        self.assertEqual(specialist_list_response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(specialist_list_response.data), 0)

        self.client.force_authenticate(user=self.client_user)
        client_list_response = self.client.get(reverse("chat-list"))
        self.assertEqual(client_list_response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(client_list_response.data), 1)

    @patch("chat_access.services.chat_list.chat_client")
    @patch("chat_access.services.chat_commands.create_stream_channel")
    def test_create_chat_restores_soft_deleted_chat(self, create_stream_channel_mock, chat_client_mock):
        chat_client_mock.query_channels.return_value = {"channels": []}

        self.client.force_authenticate(user=self.specialist_user)
        self.client.post(
            reverse("chat-soft-delete"),
            data={"channel_id": self.chat.channel_id},
            format="json",
        )

        self.client.force_authenticate(user=self.client_user)
        recreate_response = self.client.post(
            reverse("chat-list"),
            data={"specialist": self.specialist_user.id},
            format="json",
        )
        self.assertEqual(recreate_response.status_code, status.HTTP_201_CREATED)

        list_response = self.client.get(reverse("chat-list"))
        self.assertEqual(list_response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(list_response.data), 1)
        create_stream_channel_mock.assert_not_called()


class AccessOrderCancelSubscriptionTests(ChatBaseTestCase):
    def setUp(self):
        super().setUp()
        self.tariff = Tariff.objects.create(
            name="Paid plan",
            price=100,
            duration_hours=24,
            tariff_type="paid",
            specialist=self.specialist_user,
        )

    @patch("chat_access.views.access_order.update_chat_data_from_order")
    def test_client_can_cancel_active_subscription(self, update_chat_data_from_order_mock):
        now = timezone.now()
        order = AccessOrder.objects.create(
            client=self.client_user,
            specialist=self.specialist_user,
            chat=self.chat,
            tariff=self.tariff,
            payment_status="success",
            activated_at=now - timedelta(hours=1),
            expires_at=now + timedelta(hours=2),
        )
        self.client.force_authenticate(user=self.client_user)

        response = self.client.post(
            reverse("access-orders-cancel-subscription", kwargs={"pk": order.id}),
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        order.refresh_from_db()
        self.assertEqual(order.payment_status, "cancelled")
        self.assertLessEqual(order.expires_at, timezone.now())
        update_chat_data_from_order_mock.assert_called_once_with(order)

    def test_cannot_cancel_inactive_subscription(self):
        now = timezone.now()
        order = AccessOrder.objects.create(
            client=self.client_user,
            specialist=self.specialist_user,
            chat=self.chat,
            tariff=self.tariff,
            payment_status="success",
            activated_at=now - timedelta(days=2),
            expires_at=now - timedelta(days=1),
        )
        self.client.force_authenticate(user=self.client_user)

        response = self.client.post(
            reverse("access-orders-cancel-subscription", kwargs={"pk": order.id}),
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    @patch("chat_access.views.access_order.update_chat_data_from_order")
    def test_specialist_can_cancel_active_subscription_by_channel_id(self, update_chat_data_from_order_mock):
        now = timezone.now()
        order = AccessOrder.objects.create(
            client=self.client_user,
            specialist=self.specialist_user,
            chat=self.chat,
            tariff=self.tariff,
            payment_status="success",
            activated_at=now - timedelta(hours=1),
            expires_at=now + timedelta(hours=2),
        )
        self.client.force_authenticate(user=self.specialist_user)

        response = self.client.post(
            reverse("access-orders-cancel-subscription-by-channel"),
            data={"channel_id": self.chat.channel_id},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        order.refresh_from_db()
        self.assertEqual(order.payment_status, "cancelled")
        self.assertEqual(response.data["channel_id"], self.chat.channel_id)
        update_chat_data_from_order_mock.assert_called_once_with(order)

    def test_client_cannot_cancel_subscription_by_channel_id(self):
        now = timezone.now()
        AccessOrder.objects.create(
            client=self.client_user,
            specialist=self.specialist_user,
            chat=self.chat,
            tariff=self.tariff,
            payment_status="success",
            activated_at=now - timedelta(hours=1),
            expires_at=now + timedelta(hours=2),
        )
        self.client.force_authenticate(user=self.client_user)

        response = self.client.post(
            reverse("access-orders-cancel-subscription-by-channel"),
            data={"channel_id": self.chat.channel_id},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_cancel_subscription_by_channel_is_idempotent(self):
        now = timezone.now()
        order = AccessOrder.objects.create(
            client=self.client_user,
            specialist=self.specialist_user,
            chat=self.chat,
            tariff=self.tariff,
            payment_status="success",
            activated_at=now - timedelta(hours=1),
            expires_at=now + timedelta(hours=2),
        )
        self.client.force_authenticate(user=self.specialist_user)

        first_response = self.client.post(
            reverse("access-orders-cancel-subscription-by-channel"),
            data={"channel_id": self.chat.channel_id},
            format="json",
        )
        second_response = self.client.post(
            reverse("access-orders-cancel-subscription-by-channel"),
            data={"channel_id": self.chat.channel_id},
            format="json",
        )

        self.assertEqual(first_response.status_code, status.HTTP_200_OK)
        self.assertEqual(first_response.data["status"], "success")
        self.assertEqual(second_response.status_code, status.HTTP_200_OK)
        self.assertEqual(second_response.data["status"], "already_cancelled")
        order.refresh_from_db()
        self.assertEqual(order.payment_status, "cancelled")

    @patch("chat_access.views.access_order.update_chat_data_from_order")
    def test_specialist_can_cancel_active_free_subscription_by_channel_id(self, update_chat_data_from_order_mock):
        free_tariff = Tariff.objects.create(
            name="Free plan",
            price=0,
            duration_hours=24,
            tariff_type="free",
            specialist=self.specialist_user,
        )
        now = timezone.now()
        order = AccessOrder.objects.create(
            client=self.client_user,
            specialist=self.specialist_user,
            chat=self.chat,
            tariff=free_tariff,
            tariff_type="free",
            payment_status="success",
            activated_at=now - timedelta(hours=1),
            expires_at=now + timedelta(hours=2),
        )
        self.client.force_authenticate(user=self.specialist_user)

        response = self.client.post(
            reverse("access-orders-cancel-subscription-by-channel"),
            data={"channel_id": self.chat.channel_id},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        order.refresh_from_db()
        self.assertEqual(order.payment_status, "cancelled")
        update_chat_data_from_order_mock.assert_called_once_with(order)


class AccessOrderActivationTests(ChatBaseTestCase):
    def test_activate_uses_duration_hours_instead_of_fixed_minutes(self):
        tariff = Tariff.objects.create(
            name="Paid plan",
            price=100,
            duration_hours=24,
            tariff_type="paid",
            specialist=self.specialist_user,
        )
        order = AccessOrder.objects.create(
            client=self.client_user,
            specialist=self.specialist_user,
            chat=self.chat,
            tariff=tariff,
            duration_hours=2,
            payment_status="pending",
        )

        order.activate()
        order.refresh_from_db()

        self.assertIsNotNone(order.activated_at)
        self.assertIsNotNone(order.expires_at)
        self.assertEqual(order.expires_at - order.activated_at, timedelta(hours=2))
