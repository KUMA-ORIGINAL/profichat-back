# Свой мессенджер и звонки вместо GetStream — дизайн

Дата: 2026-10-25. Статус: черновик на согласование.

## 1. Зачем

Сейчас переписка между клиентом и специалистом живёт в GetStream (платный сервис).
Задача — **отказаться от GetStream** и не зависеть от платных сервисов: чаты, голосовые,
аудио- и видеозвонки работают на **своих серверах и нашем коде**. Готовые open-source
компоненты использовать можно. Решение должно **масштабироваться** и быть современным.

Клиент — мобильное приложение на Flutter, его переводит на новое API отдельный разработчик.
Историю переписки из GetStream **нужно перенести**.

## 2. Цели / не-цели / анти-цели

**Цели**
- Чат 1:1 клиент ↔ специалист: текст, фото/видео/файлы, голосовые, ответ на сообщение,
  редактирование и удаление своего сообщения, прочитано/непрочитано, «печатает…»,
  системные сообщения о тарифе, приветствие специалиста при создании чата.
- Аудио- и видеозвонки 1:1 внутри чата, входящий звонок при закрытом приложении.
- Пуши о новых сообщениях и пропущенных звонках.
- Перенос всей истории из GetStream (сообщения, вложения, прочитанность).
- Горизонтальное масштабирование каждого компонента без переделки.
- Документация API и событий для Flutter-разработчика в стиле существующих `*_API.md`.

**Не-цели (сейчас)**
- Групповые чаты и групповые звонки.
- Реакции, закрепы, пересылка, поиск по сообщениям — добавим, когда Flutter-разработчик
  подтвердит, что они используются (модель данных их не блокирует).
- Запись звонков (LiveKit Egress можно включить позже).
- Веб-клиент.

**Анти-цели (провал, даже если «работает»)**
- Потеря или искажение истории при переносе; файлы, которые перестали открываться.
- Новая зависимость от платного SaaS (исключение — бесплатные FCM/APNs, без них пуши на
  телефон невозможны).
- Медицинская переписка/файлы доступны по угадываемой публичной ссылке.
- Долгие WebSocket-соединения на Python-воркерах Django как основа доставки.

## 3. Архитектура

```
Flutter ──REST (JWT)──▶ nginx ─▶ Django (gunicorn/uvicorn, stateless) ─▶ PostgreSQL
   │                                 │   │
   │                                 │   └─▶ Celery worker (пуши, таймауты звонков, импорт)
   │                                 ├─HTTP API─▶ Centrifugo ◀─ Redis
   │                                 ├─S3 API──▶ MinIO
   │                                 └─Server API─▶ LiveKit ◀─ Redis
   ├──WebSocket──▶ nginx ─▶ Centrifugo          (события реального времени)
   ├──PUT/GET presigned──▶ nginx ─▶ MinIO       (файлы напрямую, мимо Django)
   └──WebRTC (UDP/TURN)──▶ LiveKit              (медиа звонков)
```

Принципы:
- **Django + PostgreSQL — единственный источник истины.** Всё пишется через REST.
- **Centrifugo только доставляет** события (не хранит историю как источник). При
  переподключении клиент догружает пропущенное через REST (`after=<last_id>`).
- **Файлы идут мимо Django** — presigned URL на загрузку и скачивание.
- **Медиа звонков идут мимо Django** — LiveKit SFU со встроенным TURN.
- Медленное (пуши, внешние вызовы с ретраями, импорт) — в Celery, после `transaction.on_commit`.

Компоненты (все open-source, self-hosted, в docker-compose):

| Компонент | Зачем | Лицензия | Масштабирование |
|---|---|---|---|
| Centrifugo v6 | WebSocket-доставка, presence, «печатает» | Apache 2.0 | N нод + Redis engine |
| LiveKit server | SFU для звонков + встроенный TURN | Apache 2.0 | N нод + Redis |
| MinIO | S3-хранилище вложений | AGPLv3 (без модификации, как сервис — ок) | distributed mode |
| Celery + Redis | фоновые задачи | BSD | N воркеров |

Flutter-библиотеки (для справки разработчику): `centrifuge` (Dart), `livekit_client`,
`flutter_callkit_incoming`, `firebase_messaging`.

## 4. Модель данных (новое Django-приложение `messenger`)

Существующая `chat_access.Chat` остаётся сущностью чата; `channel_id` сохраняется как
публичный идентификатор (Flutter уже везде оперирует им). `verbose_name` поля меняется
на «Публичный ID канала».

**Chat (доп. поля)**: `last_message` (FK null), `last_message_at` (index) — для сортировки
списка и `should_reply` без JOIN по сообщениям.

**ChatMember** — состояние участника (по 2 строки на чат, создаются вместе с чатом):
`chat`, `user`, `role` (client/specialist), `last_read_message_id` (bigint null),
`unread_count` (int, денормализовано, меняется через `F()`), `muted` (bool — заменяет
Stream mute; выставляется при добавлении в чёрный список). Unique (chat, user).

**Message**: `id` BigAutoField, `chat` FK, `sender` FK null
(null = системное), `type` (`regular` | `system` | `call`), `custom_type` (для системных:
`tariffProvided` …), `text`, `reply_to` FK self null, `call` FK null, `extra_data` JSON,
`client_msg_id` UUID null (идемпотентность повторной отправки; unique (chat, sender,
client_msg_id)), `stream_id` (char null unique — для идемпотентного импорта),
`edited_at`, `deleted_at`, `created_at`. Индекс (chat, -created_at, -id) — курсор
пагинации по этой паре (импорт сохраняет исходное время сообщений).
Удаление — мягкое: текст и вложения скрываются, в ленте «Сообщение удалено».

**Attachment**: `id` UUID, `uploader` FK, `chat` FK, `message` FK null (привязывается
при отправке), `kind` (`image` | `video` | `file` | `voice`), `object_key`, `file_name`,
`mime_type`, `size`, `width`/`height`/`duration_ms`/`waveform` (JSON, метаданные от клиента),
`status` (`pending` | `ready`), `created_at`. Непривязанные `pending` старше суток чистятся
периодической задачей.

**Call**: `id` UUID, `chat`, `caller`, `callee`, `kind` (`audio` | `video`), `status`
(`ringing` | `accepted` | `declined` | `missed` | `cancelled` | `busy` | `ended` | `failed`),
`room_name`, `created_at`, `answered_at`, `ended_at`, `end_reason`, `duration_seconds`.
Каждый звонок порождает Message `type=call`, которое обновляется по завершении.

**VoipDevice**: `user`, `token` (PushKit), `bundle_id`, `active`, `created_at` —
для iOS VoIP-пушей (FCM-токены для PushKit не подходят).

Рост: при сотнях миллионов сообщений — партиционирование `messenger_message`
(hash по chat_id); сейчас не делаем, схема это допускает.

## 5. Реальное время (Centrifugo)

- `GET /api/messenger/connection-token/` → `{token, wsUrl, expiresAt}`. JWT HS256,
  `sub=user_id`, TTL 1 час; SDK сам обновляет через этот же эндпоинт.
- В токене claim `channels: ["personal:<user_id>"]` — **серверная подписка**: клиенту не
  надо подписываться вручную, все события для пользователя приходят в один поток.
  Namespace `personal` — без клиентской публикации.
- Экран открытого чата подписывается на `chat:<channel_id>` с токеном подписки
  `GET /api/chats/<channel_id>/subscription-token/` (проверка членства). В namespace
  `chat` разрешены клиентская публикация (только событие `typing`) и presence/join-leave
  («собеседник сейчас в чате»).
- Публикация из Django — HTTP API Centrifugo методом `broadcast` в личные каналы обоих
  участников, после коммита транзакции, с ретраями через Celery при ошибке.

События в `personal:*` (конверт `{type, data}`, camelCase как в REST):
`message.new`, `message.updated` (редакт/удаление/обновление звонка), `chat.read`,
`chat.updated` (тариф, заметка, избранное, ЧС, `clientCanSendVoice`), `chat.user_updated`
(замена текущего Django Channels `user_update`), `call.incoming`, `call.accepted`,
`call.declined`, `call.cancelled`, `call.ended`, `call.missed`.

## 6. REST API (под `/api/`, camelCase, ошибки — существующий формат `AppError`)

Чаты (существующий `ChatViewSet` расширяется):
- `GET chats/` — + `lastMessage`, `unreadCount`, `lastMessageAt`, `tariff` (то, что
  раньше лежало в extraData канала: `tariffName`, `activatedAt`, `expiresAt`),
  `isFavorite`, `isBlocked`, `clientCanSendVoice`; сортировка по `lastMessageAt desc`.
  `shouldReply` считается из БД.
- `GET chats/<channel_id>/` — один чат в том же формате.
- Создание, soft-delete, избранное, ЧС — без изменения контракта; вместо синка в Stream —
  событие `chat.updated`. Soft-delete скрывает чат у стороны; новое сообщение возвращает
  его (как `show` в Stream).

Сообщения:
- `GET chats/<channel_id>/messages/?before=<cursor>&limit=50` — история вниз;
  `?after=<cursor>` — догрузка после переподключения. Курсор — непрозрачная строка
  из (`created_at`, `id`), отдаётся в ответе. Ответ `{results, hasMore, nextCursor}`.
- `POST chats/<channel_id>/messages/` `{clientMsgId, text?, replyToId?, attachmentIds[]?}`
  → 201 сообщение. Повтор с тем же `clientMsgId` возвращает уже созданное.
  Проверки: членство, `clientCanSendVoice` для голосовых, непустое сообщение, вложения
  свои/из этого чата/`ready`.
- `PATCH chats/<channel_id>/messages/<id>/` `{text}` — только своё, не системное.
- `DELETE chats/<channel_id>/messages/<id>/` — только своё, мягкое.
- `POST chats/<channel_id>/read/` `{lastReadMessageId}` — монотонно, обнуляет/пересчитывает
  `unreadCount`, событие `chat.read` собеседнику.

Вложения:
- `POST chats/<channel_id>/attachments/` `{kind, fileName, mimeType, size, width?, height?,
  durationMs?, waveform?}` → `{id, uploadUrl, uploadHeaders, expiresAt}` (presigned PUT,
  15 мин). Лимиты размера по типу (настройки).
- После PUT клиент шлёт сообщение с `attachmentIds`; сервер проверяет объект (HEAD,
  размер) и ставит `ready`.
- В сообщениях вложение отдаётся с presigned GET `url` (TTL 1 час). Бакет приватный.

Системные сообщения: `POST chats/<channel_id>/system-messages/` `{customType, text?}` —
та же логика, что `send_system_message_once` (типы, тексты по умолчанию, дедуп 10 мин).
Старый путь `stream/send-system-message/` оставляем алиасом на переходный период.

Звонки:
- `POST chats/<channel_id>/calls/` `{kind}` → `{call, livekitUrl, token}`; собеседнику
  `call.incoming` + VoIP-пуш (iOS) / data-only high-priority FCM (Android).
  Если у собеседника уже идёт звонок → `busy`. Если собеседник внёс чат в ЧС → ошибка
  `CALL_NOT_ALLOWED` (*моё решение*: ЧС = «не беспокоить» и для звонков).
- `POST calls/<id>/accept/` → `{livekitUrl, token}`; `decline/`, `cancel/` (звонящий до
  ответа), `end/`.
- Таймаут звонка 45 с (Celery countdown) → `missed` + пуш «Пропущенный звонок».
- `POST /api/messenger/livekit-webhook/` — вебхуки LiveKit (подпись проверяется):
  `room_finished` / `participant_left` завершают звонок и считают длительность,
  даже если клиент не прислал `end/`.
- Комната создаётся при старте звонка с `max_participants=2`, `empty_timeout`.
- `POST /api/messenger/voip-devices/` `{token, bundleId}` — регистрация PushKit-токена.

Токены:
- `GET auth/stream-token/` и `streamToken` в ответе логина — убираются в финальной
  уборке (п. 9). Новые: `connection-token`, `subscription-token`, токен LiveKit в ответах звонков.

## 7. Пуши

- Новое сообщение → FCM-пуш получателю через существующий `send_push`, но **без записи в
  ленту Notification** (лента не для каждого сообщения) — отдельная функция
  `send_message_push`, Celery-задача. Не отправляем, если у получателя `muted`.
  `data`: `type=chat_message`, `channelId`, `messageId`, `senderName`.
  Android `tag`/iOS `thread-id` = channel_id, чтобы пуши группировались.
- Пропущенный звонок → обычный пуш + запись в ленту (`notify_user`).
- Входящий звонок: iOS — APNs VoIP (`apns-push-type: voip`, topic `<bundle>.voip`,
  .p8-ключ) через `aioapns`; Android — FCM data-only, priority high, TTL 45 с.

## 8. Перенос истории из GetStream

Management-команда `import_getstream` (идемпотентна, можно перезапускать):
1. Для каждого `Chat` с `channel_id` — постраничный `channel.query` сообщений
   (от старых к новым), с бэкоффом на rate limit.
2. Маппинг: `user.id` Stream = id в нашей БД; `type`: regular/system (+`custom_type`)/
   deleted → `deleted_at`; `parent_id`/`quoted_message_id` → `reply_to`;
   `created_at`/`updated_at`; текст как есть. Ключ идемпотентности — `stream_id`.
3. Вложения (image/video/file/audio/voiceRecording) скачиваются сразу (ссылки Stream
   временные) и кладутся в MinIO как `Attachment(status=ready)`.
4. `channel.read` → `last_read_message_id` (последнее сообщение ≤ `last_read`),
   затем пересчёт `unread_count`, `last_message`, `last_message_at`.
5. Опции: `--channel`, `--since` (дельта по времени), `--dry-run`. Отчёт: сколько каналов/
   сообщений/файлов, ошибки — в лог и итоговую сводку.

Порядок переключения (runbook в документации):
1. Деплой бэкенда с новой системой; GetStream-код пока на месте, старое приложение
   работает как прежде.
2. Полный импорт. Flutter тестирует новое приложение на staging/prod-данных.
3. Релиз приложения + принудительное обновление (минимальная версия — на стороне
   приложения/стора; если механизма нет — это задача Flutter).
4. Дельта-импорт `--since`, сверка количества сообщений по каналам.
5. Финальная уборка: удаление GetStream-кода, `stream-chat`, ключей, Django Channels
   (`ws/chats/`), отключение аккаунта GetStream.

## 9. Что удаляется в финальной уборке

`common/stream_client.py`, `account/services/stream.py`, синк пользователя в `User.save`,
`GetStreamTokenView` и `streamToken` в логине, сигнал удаления канала, команда
`update_chat_status` (данные тарифа теперь считаются из БД при запросе),
`ChatConsumer`/`routing.py`/Channels-слой (после переноса `user_update` в Centrifugo),
`STREAM_*` настройки, коды ошибок `STREAM_*` (заменяются на `MESSAGE_*`/`CALL_*`).

## 10. Инфраструктура

- docker-compose (dev и prod): `centrifugo`, `minio` (+ создание бакета), `livekit`
  (`network_mode: host` для UDP), `celery` (тот же образ backend).
- nginx: `/connection/websocket` → Centrifugo; поддомен `files.<DOMAIN>` → MinIO
  (presigned URL подписываются на этот хост); поддомен `rtc.<DOMAIN>` → LiveKit
  (wss-сигналинг). Certbot получает сертификаты и на поддомены.
- Порты на VPS: LiveKit 7881/tcp, 50000–60000/udp, TURN 3478/udp и TURN/TLS 5349.
- Все секреты — в `.env` (`CENTRIFUGO_*`, `MINIO_*`/`S3_*`, `LIVEKIT_*`, `APNS_*`),
  с описанием в `.env.example`.

## 11. Тесты

Django `APITestCase` как в `chat_access/tests.py`; клиенты Centrifugo/S3/LiveKit/APNs —
тонкие обёртки в `messenger/clients/`, в тестах мокаются. Покрываем: права доступа к чату,
пагинацию, идемпотентность отправки, unread/read, редактирование/удаление, голосовые при
запрете, вложения, системные сообщения с дедупом, жизненный цикл звонка (включая busy,
таймаут, вебхук), маппинг импорта на фикстурах ответов Stream.

## 12. Решения, принятые мной (проверьте)

- Centrifugo + LiveKit + MinIO + Celery как стек.
- Источник истины — PostgreSQL; Centrifugo не используется для истории.
- Один личный канал на пользователя для всех событий + канал чата только для «печатает»/presence.
- Реакции/закрепы/пересылка/поиск — позже, по списку от Flutter.
- ЧС блокирует и пуши, и звонки от собеседника.
- Пуши о сообщениях не пишутся в ленту уведомлений.
- Таймаут звонка 45 с; presigned PUT 15 мин, GET 1 час.

## 12a. Доступ по тарифу (решено с заказчиком)

«Активный тариф» = у чата есть `AccessOrder` с `payment_status=success` и
`expires_at > now` (та же логика, что в списке чатов).
- Тариф активен: обе стороны пишут, шлют вложения/голосовые и звонят (аудио и видео).
- Тариф не активен: **клиент** не может отправлять сообщения/вложения/голосовые и
  начинать или принимать звонки → ошибка `TARIFF_REQUIRED` (403). Чат и история видны.
- **Специалист** пишет всегда; звонить вне тарифа не может (`TARIFF_REQUIRED`).
- Системные сообщения и приветствие отправляются всегда.
- Если тариф истёк во время звонка — звонок не обрывается (*моё решение*).
- Редактирование/удаление своих сообщений и отметка «прочитано» от тарифа не зависят
  (*моё решение*).

## 12b. Масштаб

Сейчас ~10 000 пользователей → один сервер (все компоненты в docker-compose, MinIO
single-node, одна нода LiveKit). Горизонтальное расширение — без смены архитектуры.
Дата окончания GetStream неизвестна → импорт истории идёт в плане рано.

- **Сосуществование старого и нового приложения**: двусторонней синхронизации со Stream
  не делаем. Переключение — окно: принудительное обновление → дельта-импорт → новое
  приложение пишет только в нашу БД. Чтобы порядок не ломался, если импорт догоняет
  уже после первых новых сообщений, **курсор пагинации — пара (`created_at`, `id`)**,
  индекс (chat, -created_at, -id); импортированные сообщения сохраняют исходное время.
- Тестирование Flutter до релиза — на staging-копии (отдельный `.env.staging`, импорт
  туда), а не на боевом бэкенде, чтобы не слать пуши реальным людям.
- **Мобильные сети с блокировкой UDP**: TURN/TLS LiveKit выводим на 443 через
  поддомен `turn.<DOMAIN>` и SNI-маршрутизацию в nginx (`stream` + `ssl_preread`),
  без второго IP.
- Импорт — возобновляемый (прогресс по каналу сохраняется), запускается как команда,
  каналы обрабатываются по одному; файлы качаются потоково.
- Удаление аккаунта: поведение не меняем (сейчас по умолчанию мягкое удаление,
  история сохраняется). Шифрование MinIO на диске (SSE-S3) включаем по умолчанию.

## 13. Открытые вопросы к Flutter

- Какие функции чата реально показываются (реакции, ответы, пересылка, закрепы, поиск,
  онлайн-статус)?
- Есть ли в приложении механизм принудительного обновления?
- Bundle ID iOS и есть ли уже PushKit/CallKit в проекте.
