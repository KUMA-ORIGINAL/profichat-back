# Переход Flutter-приложения с GetStream на свой мессенджер

Для Flutter-разработчика: что убрать, на что заменить и где грабли. Контракт API — в
[MESSENGER_API.md](MESSENGER_API.md) (чаты, сообщения, вложения, события, пуш сообщения) и
[CALLS_API.md](CALLS_API.md) (звонки). Здесь — только перевод «как сейчас в приложении →
как будет», с конкретными файлами (`lib/...` по состоянию релиза 1.5.5+105).

Сервер уже работает в двух режимах: старое приложение (Stream) и новое ходят параллельно.
Ничего «включать» на бэкенде под новое приложение не нужно; staging — уже в новом режиме.

---

## 1. Что удалить

**Зависимости** (`pubspec.yaml`): `stream_chat_flutter`, `stream_chat_persistence`,
`stream_chat_localizations`, `stream_video`, `stream_video_flutter`,
`stream_video_push_notification`.
**Добавить:** `centrifuge` (события), `livekit_client` (медиа звонка),
`flutter_callkit_incoming` (CallKit/полноэкранный входящий, PushKit-токен).

**Код целиком (или переписать с нуля):**

| Файл | Что там сейчас |
|---|---|
| `providers/stream_chat_providers.dart` | `StreamChatClient`, persistence, `ChatConnect`, `ChatListSync`, `channelListControllerProvider`, `connectedStreamClientProvider`, `addDevice` |
| `providers/stream_video_providers.dart`, `stream_modules/stream_connection/stream_video_initializer.dart` | `StreamVideo`, `addDevice` для звонков |
| `presentation/screens/chat/providers/stream_chat_service_provider.dart` | второй вариант подключения/реконнекта Stream |
| `core/utils/stream_video_notification_handler.dart` | MethodChannel `stream_video_notifications`, `makeCall`, обработка чат-пуша по `sender_id` |
| `presentation/screens/chat/channel/incoming_call_service.dart` | `handleRingingFlowNotifications` |
| `presentation/screens/chat/channel/call_service.dart`, звонок в `client_detail_screen.dart` | `makeCall` + `getOrCreate(ringing: true)` |
| `presentation/screens/chat/call_widgets/*` | экраны на `Call` из Stream Video — UI можно оставить, источник состояния заменить (раздел 4) |
| `core/utils/theme/stream_chat_theme.dart`, `l10n/stream_chat_locale/*` | тема и локализация стоковых виджетов |
| `data/models/user/stream_user_model.dart` | пользователь Stream |
| `providers/ws_providers/ws_providers.dart` | `wss://…/ws/chats/<chatId>/` (`user_update`) → событие `chat.user_updated` в личном канале |
| `ios/Runner/VoIPManager.swift`, `ios/Runner/copiedDelegate.swift` | закомментированные/старые PushKit-делегаты — удалить, чтобы не путали |

**Старые эндпоинты бэкенда**, которые новое приложение не вызывает:
`GET /api/auth/stream-token/` (и `streamToken` из ответов логина / `auth_interceptor.dart` /
`TelegramAuthResponse`), `POST /api/stream/send-system-message/` (`chat_repository.dart`),
`ws/chats/<chatId>/`. Поле `streamToken` в логине пока остаётся ради старых сборок —
просто не читайте его.

**Не трогать:** FCM-регистрация на нашем сервере (`/api/device/gcm/`, `CreateFcmModel`) —
по ней идут все пуши, включая новые `chat_message` и `incoming_call`. Эндпоинты чатов
(`/api/chats/`, `favorites/`, `blacklist/`, `soft-delete/`, `PATCH /api/chats/<id>/`) —
те же, что сейчас.

---

## 2. Соответствие: вызов Stream → наш API

Подключение (после логина и на каждом старте с сохранённой сессией):

```
GET /api/messenger/connection-token/ → {token, wsUrl, expiresAt, limits}
Centrifuge(wsUrl, token, getToken: → тот же эндпоинт) — личный канал подписывается сам
```

Готовый код подключения и обработки событий — MESSENGER_API.md, разделы 1.2–1.5.
`limits` — лимиты загрузки (размеры по типам, `maxAttachmentsPerMessage`), проверяйте до
резерва вложения.

| Где сейчас | Stream | Стало |
|---|---|---|
| `stream_chat_providers.dart`, `main.dart` (`connectUser` до `runApp`), `app_lifecycle_reactor.dart` (disconnect/connect на resume) | `client.connectUser(user, streamToken)`, `openConnection`, `wsConnectionStatusStream` | `connection-token` + `Centrifuge.connect()`; на resume — **не** переподключать вручную, а после `connected` догрузить (MESSENGER_API 1.5) |
| `channelListControllerProvider` | `StreamChannelListController(filter: members, sort: pinned_at, last_message_at, presence: true)` | `GET /api/chats/` (без пагинации, уже отсортирован: закреплённые, затем `lastMessageAt`), обновление по `message.new` / `chat.updated` / `chat.read` / `chat.unread` |
| `ChatListSync.synced` | «подтверждено сервером» | ответ `GET /api/chats/` и есть подтверждение; кэш — свой |
| `open_chat.dart` (`client.channel(...).watch()`, `createMockChannel`, `getOrCreateChannel`), `open_chat_with_deep_link.dart` (`_getChannel`, `extraData['isActive']`) | канал + state | `GET /api/chats/<channelId>/` (объект чата целиком: собеседник, тариф, флаги) + `GET /api/chats/<channelId>/messages/` |
| `channel_page.dart` → `StreamMessageListView` | `channel.state.messages`, пагинация SDK | история с курсорами `before` / `after`, окно `around` (MESSENGER_API 3.2) |
| `channel.sendMessage(Message(text, quotedMessageId))` | | `POST /api/chats/<channelId>/messages/` `{clientMsgId, text, replyToId, attachmentIds}` |
| `channel_page.dart` `_recordingFinishedCallback` (`type: 'voicenote'`), `chat_voice_record_button.dart` (`voiceRecording`, `duration` в с, `waveform_data` 0–1), `sendImage/sendFile` | | `POST .../attachments/` (резерв) → `PUT uploadUrl` → `attachmentIds` в отправке; голосовое — `kind: "voice"`, `durationMs`, `waveform` целыми 0–100 (MESSENGER_API 4) |
| `updateMessage` / `deleteMessage` | | `PATCH` / `DELETE /api/chats/<channelId>/messages/<id>/` |
| `markReadWhenAtTheBottom`, `channel.markRead()` | | `POST .../read/` `{lastReadMessageId}`; событие `chat.read` |
| `channel.markUnread(...)` | | `POST .../unread/` `{messageId}`; событие `chat.unread` (не вызывайте `read/` сразу после) |
| `channel.state.unreadCount`, `read` собеседника | | `unreadCount`, `lastReadMessageId`, `companionLastReadMessageId` в объекте чата |
| `channel.pin()` / `unpin()` | | `POST /api/chats/pins/add/` / `pins/remove/` `{channelId}`, `pinnedAt` |
| `keyStroke` / typing, `watcherCount` | | канал `chat:<channelId>` (подписка по `GET /api/chats/<channelId>/subscription-token/`): публикация `typing`, presence (MESSENGER_API 1.4) |
| `user.online`, `user.lastActive` | | `companion.isOnline`, `companion.lastActiveAt` (снимок при загрузке списка/чата) |
| `chat_search_provider.dart` `client.search(Filter.in_('members'), query)` | | `GET /api/messages/search/?q=` (2–100 символов), переход к результату — `?around=<id>` |
| `WhatsAppQuotedMessage` (`quotedMessage`) | | `replyTo {id, text, senderId, createdAt, deletedAt, attachment}` |
| `channel.extraData['tariffName' / 'activatedAt' / 'expiresAt']` (`info_about_tariff.dart`, `second_user_box.dart`, `channel_page.dart`) | | `tariff {name, activatedAt, expiresAt}`; активен, если `expiresAt > now` |
| `extraData['favoriteBy' / 'blockedBy' / 'specialist_note']` | | `isFavorite`, `isBlocked`, `specialistNote` |
| `channel_system_message_editor.dart` (`/api/stream/send-system-message/` + `updatePartial({'lastTariffStatusMessage'})`), `channel_page.dart` `_trySendSystemMessage` / `onCanSendMessagesChanged` | | `POST /api/chats/<channelId>/system-messages/` `{customType}`. Дедуп делает сервер: повтор того же тарифного статуса подряд и того же типа чаще раза в 10 минут не создаётся, поэтому `lastTariffStatusMessage`, `hasSystemMessageOfType` и флаги «уже отправляли в этой сессии» не нужны |
| `edit_profile_screen.dart`, `user_provider.dart` `updateUser` | синхронизация профиля в Stream | ничего: собеседники получают `chat.user_updated` |
| `ws_providers.dart` `user_update` | | `chat.user_updated` в личном канале (`user`, `changes`, `schedule`, `nonWorkingDates`) |
| `channel.hide()` | | `POST /api/chats/soft-delete/` (как сейчас) |
| `channel.mute()` | | не нужно: ЧС сам выключает пуши |

Полная таблица — MESSENGER_API.md, раздел 10.

---

## 3. Пуши

Три новых `type`. У `chat_message` и `incoming_call` **нет `source`**; `missed_call`
приходит с `source: "profichat"` и пишется в ленту уведомлений.

| `type` | Канал | `data` (в FCM все значения — строки) | По нажатию |
|---|---|---|---|
| `chat_message` | FCM с `notification` (Android `tag`, iOS `thread-id` = `channelId`) | `channelId`, `messageId`, `senderId`, `senderName` | открыть чат `channelId` |
| `incoming_call` | iOS — **VoIP (PushKit)**; Android — FCM data-only, high, TTL 45 с | `callId`, `channelId`, `kind`, `callerId`, `callerName`, `callerPhoto` (нет ключа, если фото нет) | CallKit / экран входящего |
| `missed_call` | FCM с `notification` + запись в ленте | `callId`, `channelId`, `kind`, `callerId`, `callerName`, `source` | открыть чат `channelId` |

Что поменять:

1. **`core/push/push_payload.dart` `_classify`.** Сейчас без `source` тип с точкой — Stream,
   иначе `unknown`; `chat_message` и `incoming_call` попадут в `unknown` и поведут в ленту.
   Проверяйте `type` до `source`:

   ```dart
   static PushSource _classify(String? source, String? type) {
     if (type == 'chat_message' || type == 'incoming_call') return PushSource.profichat;
     switch (source) { /* как было */ }
     ...
   }
   ```

   Ветку `PushSource.stream` (тип с точкой: `message.new`, `call.ring`) удалите после того,
   как старые пуши перестанут приходить.

2. **`core/push/push_router.dart`.** В `destinationOf` для `profichat`:
   `'chat_message' || 'missed_call' => PushDestination.chat` (при `channelId != null`),
   `'incoming_call' => PushDestination.none` (звонок показывает CallKit, не роутер).
   `_openChatByChannel` сейчас делает `client.channel(...).watch()` ради имени и фото
   собеседника — замените на `GET /api/chats/<channelId>/` (`companion`). Ключ в payload —
   `channelId` (геттер уже читает и `channelId`, и `channel_id`).

3. **Пять мест, где тап по пушу открывает чат через Stream** (временный `StreamChatClient` +
   `connectUser` + `getMessage(id)`, или `channel.watch()`) ради имени и фото собеседника для
   `SpecialistModel` — все заменить одним вызовом `GET /api/chats/<channelId>/` и `openChat`:
   - `main.dart` — фоновый обработчик, ветка `data['type'] == 'message.new'` (сам рисует
     локальное уведомление — не нужно: `chat_message` приходит с `notification`);
   - `app/app.dart` — ветка `message.new` (тап);
   - `presentation/screens/navigation/navigation_screen.dart` — обработка тапа (`data['id']`,
     `channel_id`);
   - `core/utils/stream_video_notification_handler.dart` — `_handleChatPayload` (iOS через
     MethodChannel, `sender_id` / `sender_name`);
   - `core/push/push_router.dart` — `_openChatByChannel` (`client.channel(...).watch()`, см. п. 2).
   Лучше всего свести все четыре первых в `PushRouter.handleTap` — там уже есть ожидание роутера.

   **Плюс отложенный тап (`initial_chat_payload`)** — его тоже перевести, иначе тап по пушу из
   убитого/фонового приложения теряется:
   - payload пишут `app/app.dart` (`localStorage.initialChatPayload = …`) и
     `core/utils/theme/notification_service.dart` (если контекста ещё нет);
   - читают `navigation_screen.dart` (`localStorage.initialChatPayload`) и
     `lib/app_lifecycle_reactor.dart` на каждом `resumed`: `_handleChatPayload` **сначала удаляет**
     сохранённый payload, а потом молча выходит, если нет `channel_id` / `sender_id`. У
     `chat_message` ключи `channelId` / `senderId`, поэтому реактор съест payload раньше
     `navigation_screen.dart`, и чат не откроется;
   - `notification_service.dart` `_handlePayloadNavigation` ветвится по `type == 'message.new'`
     и `channel_id` и делает `pushNamed('/chat?cid=…')` — такого маршрута в go_router нет.

   Исправление: один потребитель. Оставьте сохранение payload, а разбор везде делайте через
   `PushPayload.from(data)` (геттеры `channelId` / `senderId` читают оба стиля ключей) и
   `PushRouter.handleTap`; из `app_lifecycle_reactor.dart` чтение `initial_chat_payload` и
   `_handleChatPayload` удалите (или вызывайте там тот же `PushRouter.handleTap`), а ветку
   `message.new` в `notification_service.dart` замените на `PushRouter.handleTap`.

4. **Звонки.** Android: в `firebaseMessagingBackgroundHandler` (`main.dart`) ветку Stream
   (`handleRingingFlowNotifications`) заменить на `type == 'incoming_call'` →
   `FlutterCallkitIncoming.showCallkitIncoming(...)` (код — CALLS_API.md 5.3).
   **iOS игнорирует FCM `incoming_call`**: сервер не знает платформу FCM-токена и шлёт data-only
   на все устройства; на iOS входящий показывается **только** из VoIP-пуша (и из `call.incoming`,
   если приложение открыто).

5. **`ios/Runner/AppDelegate.swift`.**
   - Убрать `import stream_video_push_notification` и
     `StreamVideoPKDelegateManager.shared.registerForPushNotifications()`; вместо этого —
     свой `PKPushRegistry` с `pushRegistry(_:didReceiveIncomingPushWith:...)`, который **сразу**
     показывает CallKit через `flutter_callkit_incoming` (CALLS_API.md 5.1, готовый код).
     Без немедленного CallKit iOS перестаёт доставлять VoIP-пуши.
   - `willPresent`: ветки типов Stream (`call.ring`, `call.notification`, `message.new`) убрать;
     для `chat_message` возвращать `completionHandler([])` всегда. Решение «показывать ли баннер»
     принимает Dart: приложение уже забрало foreground-баннеры себе
     (`PushChannels.takeOverForegroundBanners()` в `app/app.dart`) и рисует локальное
     уведомление из `FirebaseMessaging.onMessage` — там и пропускайте `chat_message`, если открыт
     этот `channelId` (`CurrentChatTracker().isChannelOpen(channelId)`). Нативной стороне знать
     открытый чат не нужно.
   - VoIP-токен: `FlutterCallkitIncoming.getDevicePushTokenVoIP()` →
     `POST /api/messenger/voip-devices/` `{token, bundleId}` после логина и на каждом старте.

6. **Регистрация токенов.** `addDevice` в Stream (`main.dart` `_registerDeviceTokens` /
   `_setupTokenRefreshListener`, `push_notification_service.dart`, `stream_video_initializer.dart`,
   `user_provider.dart`) — удалить. FCM-токен — как сейчас, в `/api/device/gcm/`.

7. **Выход из аккаунта** (`user_provider.dart` `unauthenticate`): вместо
   `StreamVideo.instance.removeDevice` / `client.disconnectUser` —
   `DELETE /api/messenger/voip-devices/<voipToken>/` (iOS) и `centrifuge.disconnect()`.
   Без удаления VoIP-токена звонки следующему пользователю устройства будут приходить
   прежнему аккаунту, пока тот же токен не перепривяжется.

---

## 4. Звонки (LiveKit вместо Stream Video)

Подробно — CALLS_API.md. Коротко:

```
звонящий:   POST /api/chats/<channelId>/calls/ {kind: audio|video}
              → {call, livekitUrl, token}; status == busy → «Абонент занят»
            Room().connect(livekitUrl, token), микрофон (+камера)
            ждать call.accepted | call.declined | call.missed | call.cancelled
вызываемый: call.incoming {call, caller: {id, name, photo}} / VoIP / FCM incoming_call
            «Принять»   → POST /api/calls/<id>/accept/ → {livekitUrl, token} → connect
            «Отклонить» → POST /api/calls/<id>/decline/
любой:      «Положить трубку» → POST /api/calls/<id>/end/ (сервер сам решит: cancelled/declined/ended)
старт приложения / открытие из пуша → GET /api/calls/active/
```

Отличия от того, что сейчас в коде:

- **Видео или аудио — `call.kind`** (`"audio"` / `"video"`), а не custom-поле. Сейчас
  `call_service.dart` пишет `custom: {'isVideoCall': 'video'|'audio'}`, а
  `navigation_screen.dart` `_tryConsumingIncomingCallFromTerminatedState` читает
  `custom["isVideo"] as bool` — то есть видеозвонок из убитого состояния открывался как аудио.
- **Не завершать звонок, когда собеседник вышел.** `custom_call_screen.dart` сейчас вызывает
  `call.end()` на любой `StreamCallSessionParticipantLeftEvent`. В LiveKit
  `ParticipantDisconnectedEvent` бывает и при коротком обрыве сети: покажите
  «Переподключение…» и завершайте (`end/`) сами, если собеседник не вернулся ~30 с. Если
  комната опустела, сервер закроет звонок сам.
- **Кнопки «Завершить»** (`audio_call_vidget.dart`, `my_outgoing_call_widget.dart`,
  `my_video_call_widget.dart`, `custom_active_call_screen.dart`: `leave()` + `end()`) —
  `POST /api/calls/<id>/end/`, затем `room.disconnect()`.
- **Входящий из двух источников** (событие + пуш) — один и тот же `callId`: показывайте один экран.
- **Аватар звонящего** — `caller.photo` / `callerPhoto` (абсолютный URL, как `companion.photo`, или `null`). CallKit на
  iOS картинку по URL не показывает — используйте на своём экране звонка.
- Аудио → видео в том же звонке нельзя (токен не даёт камеру), демонстрации экрана нет.
- `dropIfAloneInRingingFlow`, `consumeAndAcceptActiveCall` — заменяет `GET /api/calls/active/`.

---

## 5. Подводные камни

1. **id сообщений — целые числа**, вложений и звонков — UUID-строки, чат в URL — `channelId`
   (`"chat_12_34"`), а `PATCH /api/chats/<id>/` — числовой `id`.
2. **Никогда не сортируйте сообщения по `id`.** Порядок — (`createdAt`, `id`): перенесённая из
   Stream история получила id позже новых сообщений.
3. **Время — ISO с `+06:00`** (`2026-10-26T16:47:36.272523+06:00`), а не `Z`. Парсите
   `DateTime.parse` и сравнивайте как моменты; строку `createdAt` для курсора берите как есть.
4. **Ссылки на файлы (`url`) живут 1 час.** Кэшируйте файлы по `id` вложения, а не по URL;
   истёкшую ссылку обновляет любая повторная загрузка сообщения. `CachedNetworkImage`
   (`ProfigramImageCacheManager` в `image_cache_manager.dart`) по умолчанию кэширует по URL, а
   подпись в URL каждый раз новая — передавайте `cacheKey: attachment.id`.
5. **Голосовые:** `waveform` — целые 0–100 (сейчас рекордер даёт 0–1 → умножить на 100),
   длительность — `durationMs` в миллисекундах (сейчас `duration` в секундах). Перенесённые
   из Stream голосовые (`voiceRecording` и старые `voicenote`) уже в этом формате.
6. **Превью и миниатюры сервер не делает:** у фото и видео один `url` на полный файл. Для
   ленты уменьшайте на клиенте; `width` / `height` — то, что прислал отправитель.
7. **Превью ссылок и черновики — на клиенте.** Сервер их не хранит (из Stream перенесён
   только текст со ссылкой).
8. **Реакций, тредов, закреплённых сообщений, жалоб (flag) нет.** Перенесённые треды стали
   ответами (`replyTo`). В меню долгого нажатия (сейчас стоковое `StreamMessageListView`)
   оставьте только «Ответить», «Копировать», «Изменить» / «Удалить» (свои), «Пометить
   непрочитанным».
9. **Сокет ничего не хранит.** После каждого `connected` и выхода из фона — `GET /api/chats/`
   и `?after=` для открытого чата (MESSENGER_API 1.5). Отдельный «синхронизирован ли список»
   (`ChatListSync`) не нужен.
10. **`unreadCount` событием не приходит** — увеличивайте сами на `message.new` от собеседника
    с `type: "regular"` в неоткрытом чате; точное значение — из `GET /api/chats/`.
11. **Ретрай отправки — с тем же `clientMsgId`**; локальное «отправляется…» сопоставляйте с
    `message.new` по `clientMsgId`.
12. **`payment_webview.dart`** ждёт подключения сокета GetStream (`_ensureStreamConnected`,
    `connectedStreamClientProvider`) перед возвратом в чат. Замените на
    `GET /api/chats/<channelId>/`: в ответе уже свежий `tariff`; `chat.updated` придёт и сам.
    Сообщение `tariffActivated` после оплаты по-прежнему шлёт приложение (`system-messages/`).
13. **Системные сообщения** — `type: "system"`, `senderId: null`, `customType`
    (`tariffProvided`, `tariffExpired`, `tariffActivated`, `chatBlocked`). Флага `isSystem` и
    текстового распознавания (`channel_system_message_editor.dart`) больше нет — при импорте
    сервер сам превратил такие сообщения в `system`. **`customType` может быть `""`**: старые
    системные сообщения без типа (или с неизвестным типом) — рисуйте их обычным системным
    пузырём с `text`, не прячьте и не пытайтесь угадать тип по тексту.
17. **Фото — абсолютные URL.** `companion.photo` в `GET /api/chats/`, `user.photo` /
    `profession.photo` / `organization.logo` в `chat.user_updated`, `caller.photo` и
    `callerPhoto` в звонках — готовые `https://<DOMAIN>/media/...` (или `null`), ничего не
    приклеивать. Не путать с полями, которые старое приложение склеивает само (например,
    `'https://profichat.operator.kg${…photo}'` в `payment_screen.dart` для заказа — это другой
    эндпоинт, он не менялся).
14. **Звонки в ленте** — сообщения `type: "call"` с объектом `call` (статус меняется через
    `message.updated`); пуш о новом сообщении для них не приходит.
15. **Тариф:** клиент без активного тарифа получает `403 TARIFF_REQUIRED` на отправку, вложения
    и звонки; история, «прочитано», правка и удаление — без тарифа.
16. **`companion.isOnline` — снимок**, событий «вышел/вошёл» нет; в открытом чате —
    presence канала `chat:<channelId>`. Чёрный список статус не скрывает: клиент видит
    «в сети» / `lastActiveAt` специалиста как обычно и не может по ним понять, что он в ЧС.

---

## 6. Порядок работ

1. Слой API и модели: чат, сообщение (с `replyTo`, вложениями, `call`), звонок; курсоры.
2. Centrifugo: подключение, токены, разбор всех событий из MESSENGER_API 7, догрузка после
   переподключения. Проверять на staging двумя аккаунтами.
3. Список чатов на `GET /api/chats/` (закреплённые, непрочитанные, тариф, «нужно ответить»).
4. Экран чата: история, отправка, ответы, правка/удаление, прочитано/непрочитано, typing.
5. Вложения и голосовые (резерв → `PUT` → отправка, кэш по `id`).
6. Системные сообщения через `system-messages/`; убрать `lastTariffStatusMessage`.
7. Пуши `chat_message`: `_classify`, `PushRouter`, пять мест с временным клиентом,
   `AppDelegate.willPresent`.
8. Звонки: LiveKit, CallKit/PushKit на iOS, FCM data-only на Android, `calls/active/`.
9. Поиск, `around`, закрепление чатов, «был(а) в сети».
10. Выход из аккаунта (VoIP-токен, Centrifugo), `payment_webview.dart`.
11. Удалить пакеты Stream и мёртвый код (раздел 1); собрать iOS без
    `stream_video_push_notification`.

---

## 7. Чек-лист

- [ ] Нет импортов `stream_chat*` / `stream_video*`, нет `StreamChatClient` и `StreamVideo`.
- [ ] `streamToken` нигде не читается; нет `/api/stream/...` и `ws/chats/`.
- [ ] Подключение к Centrifugo после логина и на старте; `getToken` обновляет токен;
      отключение при выходе.
- [ ] Все события раздела 7 MESSENGER_API обработаны, включая `chat.unread`,
      `chat.user_updated`, `call.*`.
- [ ] После `connected` и resume — `GET /api/chats/` и `?after=` в открытом чате.
- [ ] Сообщения упорядочены по (`createdAt`, `id`), id — `int`.
- [ ] Отправка с `clientMsgId` и ретраями; вложения через резерв, лимиты из `limits`.
- [ ] Голосовые: `durationMs`, `waveform` 0–100.
- [ ] Файлы кэшируются по `id` вложения.
- [ ] Прочитано / непрочитано / галочки / разделитель «Новые».
- [ ] Системные сообщения только через `system-messages/`, без `lastTariffStatusMessage`.
- [ ] `_classify` и `PushRouter` знают `chat_message`, `incoming_call`, `missed_call`; тап по
      пушу открывает чат через `GET /api/chats/<channelId>/`.
- [ ] iOS: VoIP-пуш → CallKit сразу; VoIP-токен регистрируется и удаляется при выходе;
      FCM `incoming_call` на iOS игнорируется.
- [ ] Android: FCM data-only `incoming_call` показывает полноэкранный входящий.
- [ ] Звонок: `kind`, `end/` на «положить трубку», нет `end` на уход собеседника,
      `calls/active/` на старте.
- [ ] В меню сообщения нет реакций, тредов, закрепления, жалобы.
- [ ] `payment_webview.dart` не ждёт Stream.
- [ ] Прогон на staging: два устройства (iOS + Android), переписка, вложения, голосовые,
      звонок в обе стороны из фона и из убитого приложения, оплата тарифа.
