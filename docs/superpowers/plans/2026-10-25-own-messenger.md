# Свой мессенджер и звонки — план реализации

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Новое Django-приложение `messenger`: переписка, вложения, звонки и импорт истории из GetStream на своих серверах; GetStream-код остаётся до переключения.

**Architecture:** Django + PostgreSQL — источник истины; доставка в реальном времени через Centrifugo (HTTP API `broadcast` в личные каналы `personal:<user_id>`); файлы — MinIO по presigned URL; звонки — LiveKit; медленное — Celery. Внешние сервисы спрятаны за тонкими клиентами в `messenger/clients/`, в тестах они мокаются.

**Tech Stack:** Django 5.1, DRF + camel-case, PostgreSQL 16, Redis, Celery 5, Centrifugo v6, MinIO (boto3), LiveKit (`livekit-api`), PyJWT, aioapns, firebase_admin (уже есть).

**Spec:** `docs/superpowers/specs/2026-10-25-own-messenger-design.md`

## Global Constraints

- Ничего из GetStream не удаляем в этом плане (раздел 9 спеки — отдельная уборка после переключения). Новый код не вызывает GetStream, кроме команды импорта.
- Публичный идентификатор чата в URL и событиях — `Chat.channel_id`.
- Ответы — camelCase (рендерер уже настроен); ошибки — `AppError(message, code=ErrorCode.X, status_code=...)`.
- Активный тариф: `chat.access_orders.filter(payment_status="success", expires_at__gt=now).exists()`.
- Клиент без активного тарифа: нельзя отправлять сообщения/вложения/голосовые, начинать и принимать звонки → `TARIFF_REQUIRED` (403). Специалист пишет всегда, звонит только при активном тарифе. Системные сообщения и приветствие — всегда. Редактирование, удаление, «прочитано» — без тарифа.
- Таймаут звонка 45 с; presigned PUT 15 мин; presigned GET 1 час; connection-token TTL 1 час.
- Системные `custom_type`: `tariffProvided`, `tariffExpired`, `tariffActivated`, `chatBlocked`; тексты по умолчанию и дедуп 600 с — как в `account/services/stream.py`.
- Публикация в Centrifugo и пуши — только в `transaction.on_commit`; ошибка Centrifugo не ломает запрос (лог + ретрай задачей).
- Тесты: `sh <scratchpad>/t.sh <labels>` (локальные Postgres :5544 и Redis :6391, `DEBUG=1`, `--keepdb`). В тестах `CELERY_TASK_ALWAYS_EAGER=True`, клиенты `messenger.clients.*` мокаются `unittest.mock.patch`.

## Review Focus

1. Повторная отправка при плохой сети (тот же `clientMsgId`) не создаёт дубль и не шлёт второй пуш → тест `test_send_is_idempotent_by_client_msg_id` (Task 4).
2. Курсорная пагинация, когда импортированные сообщения получили id больше нативных → `test_history_orders_by_created_at_not_id` (Task 4).
3. Чужой пользователь угадывает `channel_id`/`attachment_id`/`call_id` → 404 → `test_non_member_gets_404` (Task 4), `test_cannot_attach_foreign_attachment` (Task 5), `test_non_participant_cannot_accept_call` (Task 7).
4. Одновременно две стороны звонят друг другу / второй входящий во время разговора → `busy` → `test_second_call_while_active_is_busy` (Task 7).
5. Импорт запущен повторно или упал посередине → нет дублей, продолжает → `test_import_is_idempotent` (Task 6).

---

## File Structure

```
app/messenger/
  apps.py, admin.py, urls.py, tasks.py
  models/  __init__.py chat_member.py message.py attachment.py call.py voip_device.py
  clients/ __init__.py centrifugo.py storage.py livekit.py apns.py
  services/ __init__.py access.py events.py messages.py read_state.py attachments.py
            system_messages.py calls.py push.py getstream_import.py
  serializers/ __init__.py message.py attachment.py call.py
  views/   __init__.py realtime.py messages.py attachments.py system_messages.py calls.py
           livekit_webhook.py voip_devices.py
  management/commands/import_getstream.py
  tests/   __init__.py base.py test_*.py
app/config/celery.py            (новый)
app/config/settings.py          (настройки сервисов)
app/chat_access/...             (точечные правки: список чатов, создание чата, события)
infra: docker-compose*.yml, centrifugo/config.json, livekit/livekit.yaml, nginx/nginx.conf, .env.example
docs: MESSENGER_API.md, CALLS_API.md, MESSENGER_MIGRATION.md, API_ERROR_CODES.md, README.md
```

---

### Task 1: Каркас приложения, зависимости, настройки, Celery, инфраструктура

**Files:**
- Create: `app/messenger/{__init__,apps,admin,urls,tasks}.py`, `app/messenger/tests/{__init__,base}.py`, `app/config/celery.py`, `centrifugo/config.json`, `livekit/livekit.yaml`
- Modify: `app/requirements.txt`, `app/config/settings.py`, `app/config/__init__.py`, `app/config/urls.py`, `docker-compose.yml`, `docker-compose.prod.yml`, `.env.example`

**Interfaces:**
- Produces: настройки `CENTRIFUGO_API_URL`, `CENTRIFUGO_API_KEY`, `CENTRIFUGO_TOKEN_SECRET`, `CENTRIFUGO_WS_URL`, `S3_ENDPOINT_URL`, `S3_PUBLIC_ENDPOINT_URL`, `S3_ACCESS_KEY`, `S3_SECRET_KEY`, `S3_BUCKET`, `S3_REGION`, `LIVEKIT_URL` (публичный wss), `LIVEKIT_API_URL` (внутренний http), `LIVEKIT_API_KEY`, `LIVEKIT_API_SECRET`, `APNS_KEY_PATH`, `APNS_KEY_ID`, `APNS_TEAM_ID`, `APNS_BUNDLE_ID`, `APNS_USE_SANDBOX`, `MESSENGER_CALL_RING_TIMEOUT_SECONDS=45`, `MESSENGER_ATTACHMENT_MAX_BYTES={"image": 20MB, "video": 200MB, "file": 50MB, "voice": 20MB}`, `CELERY_BROKER_URL=REDIS_URL+"/3"`. Все с `default=""`/разумным default, чтобы dev/test стартовали без них.
- Produces: `messenger.tests.base.MessengerTestCase(APITestCase)` с `self.client_user`, `self.specialist`, `self.chat` (через `create_or_get_chat`, Stream замокан), `self.activate_tariff(hours=24) -> AccessOrder`, `self.auth(user)`; патчит `messenger.clients.centrifugo.broadcast` в `self.broadcast_mock` и `User.upsert_stream_user` (чтобы тесты не ходили в сеть).

- [ ] **Step 1:** requirements: `celery==5.4.0`, `boto3==1.35.*`, `livekit-api==0.8.*`, `aioapns==3.3.*` (PyJWT уже есть транзитивно — добавить явно `PyJWT==2.10.1`). Установить в `.venv`.
- [ ] **Step 2:** `config/celery.py` (стандартный `Celery("config")`, `config_from_object("django.conf:settings", namespace="CELERY")`, autodiscover), импорт в `config/__init__.py`. `REDIS_URL` уже читается из env (сделано).
- [ ] **Step 3:** `INSTALLED_APPS += ["messenger"]`, `path("api/", include("messenger.urls"))`.
- [ ] **Step 4:** docker-compose (dev и prod): сервисы `centrifugo` (`centrifugo/centrifugo:v6`, конфиг смонтирован, Redis engine на `redis:6379` db 4), `minio` (`minio/minio`, `server /data --console-address :9001`, том `minio-data`) + одноразовый `minio-init` (`minio/mc`: создать бакет `S3_BUCKET`, приватный, SSE-S3), `livekit` (`livekit/livekit-server`, `network_mode: host` в prod, Redis, встроенный TURN, конфиг), `celery` (образ backend, `celery -A config worker -l info`).
- [ ] **Step 5:** `centrifugo/config.json`: `client.token.hmac_secret_key` из env, `http_api.key` из env, namespaces: `personal` (`allow_subscribe_for_client: false`, presence: true), `chat` (`allow_publish_for_subscriber: true`, `presence: true`, `join_leave: true`, `force_push_join_leave: true`). Публикация клиентом в `chat:*` разрешена только с subscription-token (у `chat` нет `allow_subscribe_for_client`).
- [ ] **Step 6:** `.env.example` — все новые переменные с комментариями (стиль файла).
- [ ] **Step 7:** Проверка: `sh t.sh messenger` → `Ran 0 tests`/OK, `python manage.py check` без ошибок; `docker compose config` валиден.
- [ ] **Step 8:** Commit `feat(messenger): scaffold app, settings, celery and infra services`.

### Task 2: Модели и участники чата

**Files:**
- Create: `app/messenger/models/*.py`, миграции `messenger/0001_initial`, `messenger/0002_backfill_members` (data), `chat_access/00xx_chat_last_message`
- Modify: `app/chat_access/models/chat.py`, `app/chat_access/services/chat_commands.py`, `app/account/services/invite_client.py`, `app/messenger/admin.py`
- Test: `app/messenger/tests/test_models.py`

**Interfaces:**
- Produces модели (поля — спека §4): `ChatMember(chat, user, role, last_read_message_id, unread_count, muted)`, `Message(chat, sender, type, custom_type, text, reply_to, call, extra_data, client_msg_id, stream_id, edited_at, deleted_at, created_at)` с `Message.Type.REGULAR|SYSTEM|CALL`, `Attachment(... kind, status ...)` с `Attachment.Kind.IMAGE|VIDEO|FILE|VOICE`, `Attachment.Status.PENDING|READY`, `Call(...)` с `Call.Status.*`, `Call.Kind.AUDIO|VIDEO`, `Call.ACTIVE_STATUSES = (RINGING, ACCEPTED)`, `VoipDevice(user, token, bundle_id, active)`.
- `Message.created_at` — `DateTimeField(default=timezone.now, db_index=False)` (не auto_now_add: импорт ставит исходное время). Индекс `(chat, -created_at, -id)`. Unique `(chat, sender, client_msg_id)` с условием `client_msg_id IS NOT NULL`.
- `Chat.last_message` (FK `messenger.Message`, null, SET_NULL, related_name="+"), `Chat.last_message_at` (null, db_index).
- `messenger.services.members.ensure_members(chat) -> None` (в `services/__init__`): get_or_create двух `ChatMember` (client/specialist).
- `Chat.member_for(user) -> ChatMember | None`.

- [ ] **Step 1: тесты** `test_ensure_members_creates_two_rows_idempotently` (дважды → 2 строки, роли client/specialist); `test_create_or_get_chat_creates_members`; `test_backfill_migration_creates_members_for_existing_chats` (через `MigrationExecutor` или вызов функции миграции `backfill(apps, schema_editor)` напрямую).
- [ ] **Step 2:** запустить — FAIL.
- [ ] **Step 3:** модели, миграции, `ensure_members`, вызов в `create_or_get_chat` (после создания и в ветке «существует») и в `invite_client` после `get_or_create` чата. Admin: `MessageAdmin` (read-only, фильтр по type), `CallAdmin`.
- [ ] **Step 4:** PASS, плюс `sh t.sh chat_access account` без новых падений.
- [ ] **Step 5:** Commit `feat(messenger): message, attachment, call models and chat members`.

### Task 3: Centrifugo-клиент, события, токены, доступ по тарифу

**Files:**
- Create: `messenger/clients/centrifugo.py`, `messenger/services/{events,access}.py`, `messenger/views/realtime.py`
- Modify: `common/errors.py`, `messenger/urls.py`
- Test: `messenger/tests/test_realtime.py`, `messenger/tests/test_access.py`

**Interfaces:**
- `clients.centrifugo.broadcast(channels: list[str], data: dict) -> None` — POST `{CENTRIFUGO_API_URL}/api/broadcast`, заголовок `X-API-Key`, timeout 3 с, исключение `CentrifugoError` при не-2xx.
- `clients.centrifugo.connection_token(user_id: int) -> tuple[str, datetime]` — HS256, `sub=str(user_id)`, `exp`, `channels=[f"personal:{user_id}"]`.
- `clients.centrifugo.subscription_token(user_id: int, channel: str) -> str` — HS256, `sub`, `channel`, `exp`.
- `services.events.personal_channel(user_id) -> str`; `services.events.publish(user_ids: Iterable[int], event_type: str, data: dict) -> None` — on_commit → `broadcast(...)` с конвертом `{"type": event_type, "data": camelize(data)}` (`djangorestframework_camel_case.util.camelize`); при `CentrifugoError` — `tasks.publish_event.apply_async(..., countdown=2, max_retries=5)`.
- `services.access.has_active_tariff(chat, now=None) -> bool`; `ensure_member(user, channel_id) -> Chat` (404 `CHAT_NOT_FOUND`, если не участник); `ensure_can_send(chat, user) -> None`; `ensure_can_send_voice(chat, user) -> None` (клиент и `client_can_send_voice=False` → 403 `VOICE_NOT_ALLOWED`); `ensure_can_call(chat, user) -> None`.
- Новые `ErrorCode`: `TARIFF_REQUIRED`, `VOICE_NOT_ALLOWED`, `MESSAGE_NOT_FOUND`, `MESSAGE_EDIT_FORBIDDEN`, `MESSAGE_EMPTY`, `ATTACHMENT_INVALID`, `ATTACHMENT_TOO_LARGE`, `CALL_NOT_FOUND`, `CALL_NOT_ALLOWED`, `CALL_INVALID_STATE`, `REALTIME_UNAVAILABLE`.
- Эндпоинты: `GET api/messenger/connection-token/` → `{token, wsUrl, expiresAt}`; `GET api/chats/<channel_id>/subscription-token/` → `{token, channel}` (channel = `chat:<channel_id>`).

- [ ] **Step 1: тесты**: `test_connection_token_contains_personal_channel` (декодировать PyJWT секретом из settings: `sub`, `channels == ["personal:<id>"]`, `exp` ≈ now+3600); `test_subscription_token_requires_membership` (чужой → 404); `test_publish_sends_after_commit_with_camelized_envelope` (`captureOnCommitCallbacks(execute=True)`, проверить вызов `broadcast(["personal:1","personal:2"], {"type": "message.new", "data": {"channelId": ...}})`); `test_publish_failure_schedules_retry`; access: `test_client_without_tariff_cannot_send` (TARIFF_REQUIRED 403), `test_specialist_without_tariff_can_send`, `test_specialist_without_tariff_cannot_call`, `test_client_voice_forbidden_when_disabled`.
- [ ] **Step 2:** FAIL. **Step 3:** реализация. **Step 4:** PASS.
- [ ] **Step 5:** Commit `feat(messenger): realtime tokens, event publishing, tariff access rules`.

### Task 4: Сообщения: история, отправка, редактирование, удаление, прочитано, список чатов, пуши

**Files:**
- Create: `messenger/services/{messages,read_state,push}.py`, `messenger/serializers/message.py`, `messenger/views/messages.py`
- Modify: `chat_access/services/chat_list.py`, `chat_access/serializers/chat.py`, `chat_access/views/chat.py`, `messenger/tasks.py`, `common/notifications.py`
- Test: `messenger/tests/test_messages.py`, `messenger/tests/test_chat_list.py`

**Interfaces:**
- `services.messages.send_message(chat, sender, *, text: str, client_msg_id: UUID | None, reply_to_id: int | None, attachment_ids: list[UUID]) -> Message` — в транзакции: идемпотентность по `client_msg_id` (вернуть существующее без событий), создание, привязка вложений (Task 5 добавит проверку; здесь — параметр принимается), `chat.last_message/_at`, `ChatMember.unread_count = F()+1` у собеседника, возврат чата из soft-delete у обеих сторон (обнулить `deleted_by_*_at`); on_commit: `publish([client, specialist], "message.new", MessageSerializer)` и `tasks.send_message_push.delay(message.id)`.
- `services.messages.create_system_message(chat, custom_type: str, text: str, extra_data: dict | None = None) -> Message` — sender=None, type=SYSTEM, те же side-effects, но без пуша и без unread.
- `services.messages.edit_message(message, user, text) -> Message` / `delete_message(message, user) -> Message` — только автор, не SYSTEM/CALL, иначе `MESSAGE_EDIT_FORBIDDEN` 403; событие `message.updated`.
- `services.read_state.mark_read(chat, user, message_id: int) -> ChatMember` — монотонно (меньший id игнорируется), `unread_count` = число сообщений собеседника после этого сообщения по (created_at, id); событие `chat.read` `{channelId, userId, lastReadMessageId}` собеседнику и себе (синхронизация устройств).
- `services.messages.list_messages(chat, *, before: str | None, after: str | None, limit: int) -> tuple[list[Message], bool, str | None]` — курсор `base64url("<created_at iso>|<id>")`; `before` — по убыванию, `after` — по возрастанию; limit ≤ 100, по умолчанию 50.
- `MessageSerializer` поля: `id, channelId, senderId, type, customType, text (пусто, если deleted), replyTo {id, senderId, text, type} | null, attachments [...] (Task 5), call (Task 7), extraData, editedAt, deletedAt, createdAt, clientMsgId`.
- `services.push.send_message_push(message_id: int) -> None` — получатель = собеседник; не слать, если `ChatMember.muted`; `send_push(user, title=<имя отправителя>, message=<текст или «Голосовое сообщение»/«Фото»/«Файл»>, extra={"type": "chat_message", "channelId", "messageId", "senderId"}, collapse/thread = channel_id)` — добавить в `common/notifications.send_push` необязательный `thread_id: str | None` (Android `tag`, APNs `thread_id`), без записи в ленту.
- URL (`messenger/urls.py`): `chats/<channel_id>/messages/` GET/POST, `chats/<channel_id>/messages/<int:pk>/` PATCH/DELETE, `chats/<channel_id>/read/` POST.
- Список чатов: `build_chat_list_item` получает поля `last_message` (сериализованное сообщение или null), `last_message_at`, `unread_count` (из `ChatMember`), `is_favorite`, `is_blocked`, `client_can_send_voice`, `tariff {name, activatedAt, expiresAt} | null`; `should_reply` из БД: последнее сообщение не системное/не call и `sender_id != user.id`. `get_should_reply_map` больше не ходит в Stream. Сортировка `F("last_message_at").desc(nulls_last=True), -created_at`. Добавить `GET chats/<channel_id>/` (retrieve по `channel_id`, только участник).
- Блэклист: `add_blacklist`/`remove_blacklist` дополнительно ставят/снимают `ChatMember.muted` у текущего пользователя (Stream mute оставить).

- [ ] **Step 1: тесты** (все через API): `test_send_message_returns_201_and_publishes_to_both`, `test_send_is_idempotent_by_client_msg_id` (два POST → один Message, один `send_message_push`), `test_client_without_tariff_gets_tariff_required`, `test_empty_message_rejected` (MESSAGE_EMPTY), `test_reply_to_must_be_same_chat`, `test_history_pagination_before_and_after`, `test_history_orders_by_created_at_not_id` (создать сообщение с бóльшим id, но более ранним created_at — оно идёт раньше), `test_non_member_gets_404`, `test_edit_own_message`, `test_cannot_edit_others_or_system`, `test_delete_hides_text_and_publishes_updated`, `test_mark_read_is_monotonic_and_resets_unread`, `test_new_message_unhides_soft_deleted_chat`, `test_push_skipped_when_recipient_muted`; список: `test_chat_list_has_last_message_unread_and_should_reply_from_db`, `test_chat_list_sorted_by_last_message_at`, `test_chat_list_tariff_block`. Существующие `ChatShouldReplyTests` переписать на данные БД (они мокали Stream).
- [ ] **Step 2:** FAIL. **Step 3:** реализация. **Step 4:** `sh t.sh messenger chat_access` PASS.
- [ ] **Step 5:** Commit `feat(messenger): messages API, read state, chat list from DB, message pushes`.

### Task 5: Вложения (MinIO)

**Files:**
- Create: `messenger/clients/storage.py`, `messenger/services/attachments.py`, `messenger/serializers/attachment.py`, `messenger/views/attachments.py`
- Modify: `messenger/services/messages.py`, `messenger/serializers/message.py`, `messenger/tasks.py`, `config/celery.py` (beat-расписание очистки)
- Test: `messenger/tests/test_attachments.py`

**Interfaces:**
- `clients.storage.presigned_put(key: str, content_type: str, expires: int) -> str`, `presigned_get(key: str, expires: int, file_name: str) -> str` (с `ResponseContentDisposition`), `head(key: str) -> dict | None` (`ContentLength`), `put_stream(key: str, fileobj, content_type: str) -> None`, `delete(key: str) -> None`. Подпись на `S3_PUBLIC_ENDPOINT_URL` (внешний хост), операции — на `S3_ENDPOINT_URL`.
- Ключ объекта: `chats/<chat_id>/<uuid>/<safe_file_name>`.
- `services.attachments.create_upload(chat, user, *, kind, file_name, mime_type, size, width=None, height=None, duration_ms=None, waveform=None) -> tuple[Attachment, str, datetime]` — проверка `ensure_can_send` (+ `ensure_can_send_voice` для voice), лимит `MESSENGER_ATTACHMENT_MAX_BYTES[kind]` → `ATTACHMENT_TOO_LARGE` 413.
- `services.attachments.claim_for_message(chat, user, attachment_ids) -> list[Attachment]` — каждое: тот же chat и uploader, `message is None`, объект есть (`head`) и размер ≤ заявленного лимита → `READY`; иначе `ATTACHMENT_INVALID` 400. Вызывается внутри `send_message`; voice в составе → `ensure_can_send_voice`.
- `AttachmentSerializer`: `id, kind, fileName, mimeType, size, width, height, durationMs, waveform, url` (presigned GET 3600).
- `tasks.cleanup_pending_attachments()` — удалить `PENDING` и непривязанные старше 24 ч (+ объект в S3); beat ежечасно.
- URL: `POST chats/<channel_id>/attachments/` → `{id, uploadUrl, uploadHeaders: {"Content-Type": mime}, expiresAt}`.

- [ ] **Step 1: тесты**: `test_create_upload_returns_presigned_url`, `test_voice_upload_forbidden_when_disabled`, `test_too_large_rejected`, `test_send_with_attachment_marks_ready_and_serializes_url`, `test_missing_object_rejected`, `test_cannot_attach_foreign_attachment` (чужой uploader или другой чат → ATTACHMENT_INVALID), `test_message_with_only_attachment_not_empty`, `test_cleanup_removes_stale_pending`.
- [ ] **Step 2–4:** FAIL → реализация → PASS.
- [ ] **Step 5:** Commit `feat(messenger): attachments via presigned MinIO URLs`.

### Task 6: Системные сообщения, приветствие, события чата и импорт из GetStream

**Files:**
- Create: `messenger/services/system_messages.py`, `messenger/views/system_messages.py`, `messenger/services/getstream_import.py`, `messenger/management/commands/import_getstream.py`, `messenger/tests/fixtures/stream_channel.json`
- Modify: `chat_access/services/chat_commands.py`, `account/services/invite_client.py`, `chat_access/views/chat.py`, `chat_access/services/favorites.py`, `chat_access/services/chat.py`, `chat_access/views/stream_system_message.py`, `account/services/user.py`
- Test: `messenger/tests/test_system_messages.py`, `messenger/tests/test_import.py`

**Interfaces:**
- `services.system_messages.send_system_message_once(chat, custom_type: str, text: str | None = None) -> Message | None` — та же валидация типов и дедуп 600 с, но по нашей БД; `extra_data={"customType", "clientName", "specialistName"}`. `POST chats/<channel_id>/system-messages/` `{customType, text?}` (только участник) → `{success, clientName, specialistName}`. Старый `StreamSystemMessageViewSet` дополнительно вызывает новую функцию (двойная запись на переходный период).
- Приветствие: при создании чата (`create_or_get_chat`, `invite_client`) — `send_message(chat, specialist, text=invite_greeting, ...)` в обход тарифной проверки (вызов сервиса напрямую, не через `ensure_can_send`). Stream-вызов остаётся.
- `services.events.publish_chat_updated(chat) -> None` — `chat.updated` обоим с полями: `channelId, specialistNote (только специалисту — отдельные payload'ы), clientCanSendVoice, tariff, isFavorite/isBlocked (для каждого свой)`. Вызывать из: `update_chat_and_stream`, избранное, ЧС, `update_chat_data_from_order`.
- `broadcast_user_update` дополнительно публикует `chat.user_updated` (тот же payload) собеседникам через `publish`.
- Импорт: `services.getstream_import.import_channel(chat, *, since: datetime | None, dry_run: bool) -> ImportStats` (dataclass `channels, messages_created, messages_skipped, attachments, errors`), `import_all(*, channel_id=None, since=None, dry_run=False) -> ImportStats`. Постранично `channel.query(messages={"limit": 100, "created_at_after": ...})` от старых к новым; маппинг по спеке §8; `stream_id` — ключ (`update_or_create` → повтор без дублей; `deleted_at`/`edited_at` обновляются); вложения: скачивание `requests.get(stream=True)` → `storage.put_stream`, `Attachment(status=READY, message=...)`; reply — второй проход по `stream_id`; `channel.read` → `last_read_message_id` + пересчёт `unread_count`; в конце `last_message/_at`. Ошибка канала → в `errors`, продолжаем следующий. Бэкофф на HTTP 429 (sleep `Retry-After` или 2^n, до 5 попыток).
- Команда: `python manage.py import_getstream [--channel ID] [--since ISO] [--dry-run]`, печатает сводку.

- [ ] **Step 1: тесты**: `test_system_message_dedup_within_600s`, `test_system_message_invalid_type_rejected`, `test_greeting_created_without_tariff`, `test_favorite_publishes_chat_updated`, `test_user_update_published_to_companions`; импорт на фикстуре (замоканный `chat_client.channel(...).query` и `requests.get`): `test_import_maps_regular_system_deleted_and_reply`, `test_import_downloads_attachments_to_storage`, `test_import_sets_read_state_and_unread`, `test_import_is_idempotent` (два прогона → то же число сообщений), `test_import_continues_after_channel_error`.
- [ ] **Step 2–4:** FAIL → реализация → PASS (`messenger chat_access account`).
- [ ] **Step 5:** Commit `feat(messenger): system messages, chat events and GetStream history import`.

### Task 7: Звонки (LiveKit), VoIP-пуши, вебхук

**Files:**
- Create: `messenger/clients/{livekit,apns}.py`, `messenger/services/calls.py`, `messenger/serializers/call.py`, `messenger/views/{calls,livekit_webhook,voip_devices}.py`
- Modify: `messenger/tasks.py`, `messenger/services/push.py`, `messenger/serializers/message.py`, `messenger/urls.py`
- Test: `messenger/tests/test_calls.py`

**Interfaces:**
- `clients.livekit.create_room(name: str) -> None` (`max_participants=2`, `empty_timeout=60`), `access_token(user, room: str, *, video: bool) -> str` (TTL 2 ч, identity=`str(user.id)`, name=ФИО), `delete_room(name) -> None`, `verify_webhook(body: str, auth_header: str) -> dict` (`livekit.api.WebhookReceiver`).
- `clients.apns.send_voip(token: str, payload: dict) -> bool` (aioapns, `push_type=voip`, topic `APNS_BUNDLE_ID + ".voip"`, `asyncio.run`); 410 → `VoipDevice.active=False`.
- `services.calls.start_call(chat, caller, kind) -> tuple[Call, str]` — `ensure_can_call`; ЧС у собеседника → `CALL_NOT_ALLOWED` 403; есть активный (`ACTIVE_STATUSES`) звонок у caller или callee → создать Call со статусом `BUSY` и сообщение call, вернуть 201 с `status=busy` и `token=null` (клиент показывает «Абонент занят»). Иначе `RINGING`, `room_name=f"call_{call.id}"`, `create_room`, Message type=CALL; on_commit: `call.incoming` callee, `tasks.send_call_push.delay(call.id)`, `tasks.expire_call.apply_async((call.id,), countdown=45)`.
- `accept_call(call, user) -> str` (только callee, статус RINGING, `ensure_can_call` для клиента) → `ACCEPTED`, `answered_at`, событие `call.accepted` обоим. `decline_call` (callee, RINGING → DECLINED), `cancel_call` (caller, RINGING → CANCELLED), `end_call(call, user, reason="hangup")` (участник, ACCEPTED → ENDED, `duration_seconds = ended_at - answered_at`; RINGING от caller = cancel). Неверный статус → `CALL_INVALID_STATE` 409; не участник → `CALL_NOT_FOUND` 404. Каждое завершение: обновить Message call (`message.updated`), событие `call.<status>`, `delete_room`.
- `tasks.expire_call(call_id)` — если ещё RINGING → `MISSED`, пуш «Пропущенный звонок» через `notify_user(type="missed_call")`.
- `tasks.send_call_push(call_id)` — iOS: все активные `VoipDevice` callee → `send_voip`; Android/FCM: data-only сообщение `{type: "incoming_call", callId, channelId, kind, callerId, callerName}`, `android.priority=high`, `ttl=45s` (новая функция `send_data_push(user, data, ttl_seconds)` в `common/notifications.py`).
- Вебхук `POST api/messenger/livekit-webhook/` (AllowAny, подпись обязательна): `participant_left` / `room_finished` для ACCEPTED → `end_call(..., reason="disconnected")`.
- `POST api/messenger/voip-devices/` `{token, bundleId}` → upsert по token, привязка к текущему user; `DELETE api/messenger/voip-devices/<token>/`.
- `CallSerializer`: `id, channelId, callerId, calleeId, kind, status, createdAt, answeredAt, endedAt, durationSeconds, endReason`. Ответы start/accept: `{call, livekitUrl, token}`. В `MessageSerializer.call` — `CallSerializer` или null.
- URL: `POST chats/<channel_id>/calls/`, `POST calls/<uuid:pk>/{accept,decline,cancel,end}/`, `GET calls/<uuid:pk>/`.

- [ ] **Step 1: тесты**: `test_start_call_rings_and_schedules_timeout`, `test_client_without_tariff_cannot_call_or_accept`, `test_blacklisted_companion_call_not_allowed`, `test_second_call_while_active_is_busy`, `test_accept_returns_token_and_publishes`, `test_non_participant_cannot_accept_call`, `test_decline_cancel_end_transitions_and_duration`, `test_invalid_transition_409`, `test_expire_marks_missed_and_notifies`, `test_webhook_rejects_bad_signature`, `test_webhook_participant_left_ends_call`, `test_voip_device_register_and_push`, `test_call_message_in_history`.
- [ ] **Step 2–4:** FAIL → реализация → PASS.
- [ ] **Step 5:** Commit `feat(messenger): audio/video calls via LiveKit with VoIP push`.

### Task 8: nginx, документация для Flutter, runbook переключения

**Files:**
- Modify: `nginx/nginx.conf`, `nginx/nginx_entrypoint.sh` (certbot для поддоменов), `README.md`, `API_ERROR_CODES.md`, `.env.example`
- Create: `MESSENGER_API.md`, `CALLS_API.md`, `MESSENGER_MIGRATION.md`

- [ ] **Step 1:** nginx: `location /connection/websocket` → `centrifugo:8000` (upgrade-заголовки, `proxy_read_timeout 1h`); `server_name files.$DOMAIN` → `minio:9000` (`client_max_body_size 200M`, `proxy_set_header Host $http_host`, без буферизации запроса); `server_name rtc.$DOMAIN` → LiveKit `:7880` (websocket); `stream {}`-блок с `ssl_preread`: `turn.$DOMAIN` → LiveKit TURN/TLS, остальное → http-сервер на внутреннем порту. Certbot получает `$DOMAIN`, `files.`, `rtc.`, `turn.`.
- [ ] **Step 2:** `MESSENGER_API.md` — подключение Centrifugo (Dart: `centrifuge` пакет, getToken), все REST-эндпоинты с примерами запросов/ответов, все события с payload, курсоры, ошибки, логика тарифа, чек-лист «что заменить из GetStream SDK». `CALLS_API.md` — жизненный цикл звонка, диаграмма статусов, `livekit_client` + `flutter_callkit_incoming`, PushKit/FCM payload, регистрация VoIP-токена. `MESSENGER_MIGRATION.md` — runbook из спеки §8 с командами и сверкой. `API_ERROR_CODES.md` — новые коды. README — ссылки.
- [ ] **Step 3:** Проверка: `docker compose -f docker-compose.prod.yml config` валиден; `nginx -t` в собранном образе nginx (`docker build nginx` + `docker run --rm ... nginx -t` с подставленным DOMAIN).
- [ ] **Step 4:** Полный прогон `sh t.sh` (все приложения) — без новых падений относительно main.
- [ ] **Step 5:** Commit `docs(messenger): Flutter API docs, calls guide, migration runbook; nginx routes`.

---

## После переключения (отдельный план)

Удаление GetStream и Django Channels — спека §9. Делается после runbook-шага 4.
