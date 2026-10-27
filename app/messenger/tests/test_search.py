from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db import connection
from django.utils import timezone

from account.models import ROLE_CLIENT, ROLE_SPECIALIST
from chat_access.services.chat_commands import create_or_get_chat
from messenger.models import Message
from messenger.tests.base import MessengerTestCase

User = get_user_model()

SEARCH_URL = "/api/messages/search/"


class MessageSearchTests(MessengerTestCase):
    def setUp(self):
        super().setUp()
        patcher = patch("messenger.services.push.send_push")
        patcher.start()
        self.addCleanup(patcher.stop)
        self.other_specialist = User.objects.create_user(username="sp_search", password="p", role=ROLE_SPECIALIST)
        self.other_chat = create_or_get_chat(self.client_user, self.other_specialist)
        self.base = timezone.now() - timedelta(hours=1)
        self.seconds = 0

    def make(self, text, chat=None, sender=None, **extra):
        self.seconds += 1
        return Message.objects.create(
            chat=chat or self.chat,
            sender=sender if sender is not None else self.specialist,
            text=text,
            created_at=self.base + timedelta(seconds=self.seconds),
            **extra,
        )

    def search(self, user=None, **params):
        self.auth(user or self.client_user)
        return self.client.get(SEARCH_URL, params)

    def test_finds_case_insensitive_substring_in_own_chats_newest_first(self):
        first = self.make("Привет, как АНАЛИЗЫ?")
        second = self.make("анализы готовы", chat=self.other_chat, sender=self.other_specialist)
        self.make("ничего общего")

        response = self.search(q="  анализ ")
        self.assertEqual(response.status_code, 200, response.content)
        body = response.json()
        self.assertEqual([m["id"] for m in body["results"]], [second.id, first.id])
        self.assertEqual(body["results"][0]["channelId"], self.other_chat.channel_id)
        self.assertEqual(body["results"][1]["channelId"], self.chat.channel_id)
        self.assertFalse(body["hasMore"])
        # обычный объект сообщения
        self.assertIn("attachments", body["results"][0])
        self.assertIn("replyTo", body["results"][0])

    def test_only_regular_non_deleted_messages(self):
        self.make("анализ удалён", deleted_at=timezone.now())
        self.make("анализ системный", sender=None, type=Message.Type.SYSTEM)
        self.make("анализ звонок", type=Message.Type.CALL)
        regular = self.make("анализ обычный")
        body = self.search(q="анализ").json()
        self.assertEqual([m["id"] for m in body["results"]], [regular.id])

    def test_foreign_chats_are_not_searched(self):
        stranger = User.objects.create_user(username="cl_search", password="p", role=ROLE_CLIENT)
        foreign_chat = create_or_get_chat(stranger, self.specialist)
        self.make("анализ чужой", chat=foreign_chat)
        self.assertEqual(self.search(q="анализ").json()["results"], [])
        # специалист видит оба своих чата
        own = self.make("анализ свой")
        ids = [m["id"] for m in self.search(self.specialist, q="анализ").json()["results"]]
        self.assertIn(own.id, ids)
        self.assertEqual(len(ids), 2)

    def test_chat_hidden_by_caller_is_not_searched(self):
        message = self.make("анализ")
        self.chat.deleted_by_specialist_at = timezone.now()
        self.chat.save(update_fields=["deleted_by_specialist_at"])
        self.assertEqual(self.search(self.specialist, q="анализ").json()["results"], [])
        # у клиента чат не скрыт
        self.assertEqual([m["id"] for m in self.search(q="анализ").json()["results"]], [message.id])

    def test_like_wildcards_are_literal(self):
        self.make("скидка 100% сегодня")
        self.make("просто текст")
        body = self.search(q="0%").json()
        self.assertEqual(len(body["results"]), 1)
        self.assertEqual(self.search(q="__").json()["results"], [])

    def test_pagination_with_before_cursor(self):
        made = [self.make(f"анализ {i}") for i in range(5)]
        page = self.search(q="анализ", limit=2).json()
        self.assertEqual([m["id"] for m in page["results"]], [made[4].id, made[3].id])
        self.assertTrue(page["hasMore"])
        page = self.search(q="анализ", limit=2, before=page["nextCursor"]).json()
        self.assertEqual([m["id"] for m in page["results"]], [made[2].id, made[1].id])
        page = self.search(q="анализ", limit=2, before=page["nextCursor"]).json()
        self.assertEqual([m["id"] for m in page["results"]], [made[0].id])
        self.assertFalse(page["hasMore"])

    def test_default_and_max_limit(self):
        Message.objects.bulk_create(
            Message(chat=self.chat, sender=self.specialist, text=f"анализ {i}", created_at=self.base + timedelta(seconds=i))
            for i in range(55)
        )
        self.assertEqual(len(self.search(q="анализ").json()["results"]), 20)
        body = self.search(q="анализ", limit=500).json()
        self.assertEqual(len(body["results"]), 50)
        self.assertTrue(body["hasMore"])

    def test_query_validation(self):
        for params in ({}, {"q": ""}, {"q": " a "}, {"q": "я" * 101}):
            response = self.search(**params)
            self.assertEqual(response.status_code, 400, params)
            self.assertEqual(response.json()["code"], "VALIDATION_ERROR", params)
        for params in ({"q": "ab", "limit": "0"}, {"q": "ab", "limit": "x"}, {"q": "ab", "before": "garbage!!"}):
            response = self.search(**params)
            self.assertEqual(response.status_code, 400, params)
            self.assertEqual(response.json()["code"], "PARAM_INVALID", params)

    def test_query_of_100_chars_is_allowed(self):
        self.assertEqual(self.search(q="я" * 100).status_code, 200)

    def test_follows_chat_list_role_rule(self):
        # специалист, который где-то сам клиент: этот чат не в его списке — и в поиске его нет
        other = User.objects.create_user(username="sp_other_search", password="p", role=ROLE_SPECIALIST)
        chat_as_client = create_or_get_chat(self.specialist, other)
        self.make("анализ как клиент", chat=chat_as_client, sender=other)
        own = self.make("анализ свой")
        ids = [m["id"] for m in self.search(self.specialist, q="анализ").json()["results"]]
        self.assertEqual(ids, [own.id])

    def test_requires_auth(self):
        self.client.force_authenticate(user=None)
        self.assertEqual(self.client.get(SEARCH_URL, {"q": "ab"}).status_code, 401)

    def search_plan(self, query):
        """EXPLAIN реального запроса поиска (scope по чатам, ORDER BY, LIMIT) на «живых» объёмах."""
        from messenger.services import messages as message_service

        qs = message_service.search_queryset(self.client_user, query)[:21]
        sql, params = qs.query.sql_with_params()
        with connection.cursor() as cursor:
            cursor.execute(f"EXPLAIN {sql}", params)
            return " ".join(row[0] for row in cursor.fetchall())

    def test_real_search_query_uses_composite_index(self):
        # объём, при котором планировщику невыгоден перебор всех сообщений чата
        Message.objects.bulk_create(
            Message(chat=self.chat, sender=self.specialist, text=f"обычное сообщение номер {i}",
                    created_at=self.base + timedelta(seconds=i))
            for i in range(5000)
        )
        self.make("редкий анализ крови")
        with connection.cursor() as cursor:
            cursor.execute("ANALYZE messenger_message")

        plan = self.search_plan("анализ")
        self.assertIn("msg_chat_text_upper_trgm_idx", plan, plan)
        # 2 символа: триграмм нет, но поиск всё равно сужен чатами пользователя (chat_id в условии индекса)
        plan = self.search_plan("ан")
        self.assertRegex(plan, r"Index Cond: \(+chat_id = ", plan)
        self.assertNotIn("Seq Scan on messenger_message", plan)
