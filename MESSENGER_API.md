# Мессенджер: API для Flutter (замена GetStream)

Переписка клиента и специалиста теперь живёт на нашем сервере. GetStream SDK в новом
приложении не нужен: история и отправка — через REST, события в реальном времени — через
WebSocket (Centrifugo), файлы — напрямую в хранилище по одноразовым ссылкам, звонки —
LiveKit (отдельный документ [CALLS_API.md](CALLS_API.md)).

Все REST-запросы авторизованные (`Authorization: Bearer <access>`), под `/api/`, ключи в
camelCase. Ошибки — в общем формате с полем `code`, см. [API_ERROR_CODES.md](API_ERROR_CODES.md).
Время — ISO 8601 со смещением, например `2026-10-26T16:47:36.272523+06:00`.

## Адреса

| Что | Адрес | Откуда брать |
|---|---|---|
| REST | `https://<DOMAIN>/api/...` | как сейчас |
| WebSocket событий | `wss://<DOMAIN>/connection/websocket` | поле `wsUrl` ответа `connection-token` |
| Файлы (вложения) | `https://files.<DOMAIN>/...` | только готовые ссылки из API (`uploadUrl`, `url`) |
| Звонки | `wss://rtc.<DOMAIN>` | поле `livekitUrl` ответов звонков |

Адреса не зашивайте в приложение, кроме REST: остальные приходят в ответах API.

## Идентификаторы

| Сущность | Поле | Тип | Пример |
|---|---|---|---|
| Чат (в URL и событиях) | `channelId` | строка | `"chat_12_34"` (`chat_<clientId>_<specialistId>`) |
| Чат (числовой) | `id` | число | `77` — нужен только для `PATCH /api/chats/<id>/` |
| Сообщение | `id` | число | `1234` |
| Вложение | `id` | UUID-строка | `"0c4e…"` |
| Звонок | `id` | UUID-строка | `"5b1f…"` |
| Пользователь | `senderId`, `userId`, … | число | `34` |

**Главный принцип:** источник правды — REST. WebSocket только доставляет события и
ничего не хранит: всё, что пришло, пока сокета не было, приложение догружает через REST
(раздел «Переподключение»).

---

## 1. Реальное время (Centrifugo)

### 1.1. Токен подключения

```
GET /api/messenger/connection-token/
```

```json
{
  "token": "eyJhbGciOiJIUzI1NiIs...",
  "wsUrl": "wss://<DOMAIN>/connection/websocket",
  "expiresAt": "2026-10-26T17:47:36.272523+06:00"
}
```

Токен живёт 1 час. SDK сам запрашивает новый через `getToken` до истечения — вызывайте
этот же эндпоинт. `503 REALTIME_UNAVAILABLE` — сервер не настроен, повторите позже.

### 1.2. Подключение (Dart, пакет [`centrifuge`](https://pub.dev/packages/centrifuge))

```dart
import 'dart:convert';
import 'package:centrifuge/centrifuge.dart' as centrifuge;

Future<centrifuge.Client> connectRealtime(Api api) async {
  final first = await api.get('/api/messenger/connection-token/');

  final client = centrifuge.createClient(
    first['wsUrl'] as String,
    centrifuge.ClientConfig(
      token: first['token'] as String,
      // SDK вызывает это при истечении токена и при переподключении
      getToken: (centrifuge.ConnectionTokenEvent event) async {
        final res = await api.get('/api/messenger/connection-token/');
        return res['token'] as String;
        // пользователь разлогинен → throw centrifuge.UnauthorizedException();
      },
    ),
  );

  // Все события пользователя приходят сюда (личный канал подписан сервером)
  client.publication.listen((centrifuge.ServerPublicationEvent e) {
    final envelope = jsonDecode(utf8.decode(e.data)) as Map<String, dynamic>;
    onRealtimeEvent(envelope['type'] as String, envelope['data'] as Map<String, dynamic>);
  });

  // После каждого (пере)подключения — догрузить пропущенное через REST
  client.connected.listen((_) => catchUpAfterReconnect());

  await client.connect();
  return client;
}
```

Одно соединение на приложение, пока пользователь залогинен. При выходе —
`client.disconnect()`.

### 1.3. Личный канал `personal:<userId>`

Подписка серверная: токен уже содержит канал, вручную подписываться не нужно (и нельзя:
клиентская подписка/публикация в `personal:*` → ошибка Centrifugo `103 permission denied`).
Каждая публикация — конверт:

```json
{"type": "message.new", "data": { ... }}
```

Список типов и `data` — раздел 7.

### 1.4. Канал открытого чата `chat:<channelId>` — «печатает…» и «собеседник в чате»

Подписывайтесь, когда экран чата открыт, и отписывайтесь при закрытии. Токен подписки
(1 час, SDK обновляет сам):

```
GET /api/chats/<channelId>/subscription-token/
```

```json
{"token": "eyJhbGciOi...", "channel": "chat:chat_12_34"}
```

Не участник чата → `404 CHAT_NOT_FOUND`.

```dart
final sub = client.newSubscription(
  'chat:$channelId',
  centrifuge.SubscriptionConfig(
    getToken: (centrifuge.SubscriptionTokenEvent event) async {
      final res = await api.get('/api/chats/$channelId/subscription-token/');
      return res['token'] as String;
    },
  ),
);

// «печатает…»: свои публикации тоже приходят — фильтруйте по info.user
sub.publication.listen((centrifuge.PublicationEvent e) {
  final data = jsonDecode(utf8.decode(e.data));
  if (data['type'] == 'typing' && e.info?.user != '$myUserId') showTyping(); // гасить через ~5 с
});

// «собеседник в чате»
sub.join.listen((centrifuge.JoinEvent e) => markInChat(e.info.user, true));
sub.leave.listen((centrifuge.LeaveEvent e) => markInChat(e.info.user, false));

await sub.subscribe();
final presence = await sub.presence(); // кто уже в чате: presence.clients[*].user

// при наборе текста — не чаще раза в 2–3 секунды
await sub.publish(utf8.encode(jsonEncode({'type': 'typing'})));

// при закрытии экрана
await sub.unsubscribe();
client.removeSubscription(sub);
```

- `info.user` — id пользователя строкой (`"34"`).
- Presence — по соединениям: у одного пользователя может быть несколько устройств,
  группируйте по `user`.
- В канал чата клиент публикует только `{"type": "typing"}`. Сообщения через Centrifugo
  **не отправляются** — только `POST .../messages/`.
- Глобального статуса «в сети» нет: присутствие видно только внутри открытого чата.

### 1.5. Переподключение и догрузка

Centrifugo не хранит историю: события, пришедшие без соединения, потеряны. После каждого
`connected` (и после выхода приложения из фона):

1. Обновить список чатов: `GET /api/chats/` (`unreadCount`, `lastMessage`, `tariff`, флаги).
2. Для открытого чата — догрузить новые сообщения: `GET .../messages/?after=<курсор>`
   страницами, пока `hasMore = true` (курсор — раздел 3.2).
3. Обновлять уже загруженные сообщения (правки, удаления, статус звонка) после разрыва
   нужно перезагрузкой видимой страницы: событие `message.updated` могло потеряться.
4. Если идёт или мог прийти звонок — `GET /api/calls/active/` ([CALLS_API.md](CALLS_API.md)).

---

## 2. Чаты

### 2.1. Список — `GET /api/chats/`

Без пагинации, отсортирован по `lastMessageAt` (новые сверху; чаты без сообщений — в конце,
по дате создания). Чаты, скрытые этой стороной (`soft-delete`), не возвращаются, пока не
придёт новое сообщение. Параметр `?access_status=active|inactive` — фильтр для клиента по
наличию активного тарифа (как раньше).

```json
[
  {
    "id": 77,
    "channelId": "chat_12_34",
    "companion": {"id": 34, "firstName": "Анна", "lastName": "Петрова", "photo": null},
    "createdAt": "2026-10-20T14:00:00+06:00",
    "userRole": "client",
    "lastAccessOrder": {"id": 5, "activatedAt": "...", "expiresAt": "...", "tariffType": "...", "paymentStatus": "success"},
    "specialistNote": null,
    "latestInviteDelivery": null,
    "shouldReply": true,
    "lastMessage": { "...": "объект сообщения (раздел 3.1) или null" },
    "lastMessageAt": "2026-10-26T16:47:36.272523+06:00",
    "unreadCount": 2,
    "isFavorite": false,
    "isBlocked": false,
    "clientCanSendVoice": true,
    "tariff": {"name": "Месяц", "activatedAt": "2026-10-26T15:00:00+06:00", "expiresAt": "2026-11-25T15:00:00+06:00"}
  }
]
```

| Поле | Описание |
|---|---|
| `userRole` | `client` / `specialist` — роль текущего пользователя в этом чате |
| `companion` | собеседник |
| `lastMessage` | последнее сообщение любого типа (обычное, системное, звонок; удалённое — с пустым текстом и `deletedAt`) или `null` |
| `lastMessageAt` | время последнего сообщения или `null` |
| `unreadCount` | непрочитанные **обычные** сообщения собеседника (системные и звонки не считаются) |
| `shouldReply` | последнее сообщение обычное и от собеседника — «нужно ответить» |
| `isFavorite` / `isBlocked` | **свои** отметки текущего пользователя («Избранное», «Чёрный список» — только у специалиста; у клиента всегда `false`) |
| `clientCanSendVoice` | разрешил ли специалист клиенту голосовые |
| `tariff` | последний **оплаченный** доступ чата: `{name, activatedAt, expiresAt}` или `null`, если оплат не было. Отдаётся и после истечения — активен ли тариф, приложение решает само: `expiresAt > сейчас`. Истечение тарифа **событий не порождает** |
| `lastAccessOrder` | только у клиента: текущий активный заказ или `null` (как раньше) |
| `specialistNote` | только у специалиста: заметка (`""`, если пустая); у клиента `null` |
| `latestInviteDelivery` | только у специалиста: статус доставки приглашения (как раньше) |

### 2.2. Один чат — `GET /api/chats/<channelId>/`

Тот же объект, что элемент списка. Здесь в URL — **`channelId`** (строка). Возвращает чат
и тогда, когда он скрыт этой стороной. Не участник → `404 CHAT_NOT_FOUND`.

> ⚠️ Исторически `PATCH /api/chats/<id>/` (заметка специалиста, `clientCanSendVoice`)
> принимает **числовой `id`** чата, а `GET /api/chats/<channelId>/` — строковый
> `channelId`. Это один и тот же маршрут, смысл сегмента зависит от метода.

### 2.3. Без изменений контракта

Эти эндпоинты работают как раньше; вместо синхронизации с GetStream они рассылают событие
`chat.updated` обоим участникам (раздел 7):

| Запрос | Что делает |
|---|---|
| `POST /api/chats/` `{"specialist": 34}` | создать чат (клиент). Приветствие специалиста (`inviteGreeting`) приходит **первым сообщением** чата — обычное сообщение от специалиста |
| `PATCH /api/chats/<id>/` `{"specialistNote": "...", "clientCanSendVoice": false}` | только специалист; числовой `id`; → `chat.updated` |
| `POST /api/chats/soft-delete/` `{"channelId"}` | скрыть чат у себя (специалист). Новое сообщение вернёт чат обеим сторонам |
| `GET /api/chats/favorites/`, `POST .../favorites/add/`, `.../favorites/remove/` `{"channelId"}` | избранное специалиста → `chat.updated` |
| `GET /api/chats/blacklist/`, `POST .../blacklist/add/`, `.../blacklist/remove/` `{"channelId"}` | чёрный список специалиста → `chat.updated` |

Чёрный список = «не беспокоить» для того, кто внёс чат: ему не приходят пуши о сообщениях
этого чата, и собеседник не может ему позвонить (`CALL_NOT_ALLOWED`). Отправку сообщений
сервер **не запрещает**. Клиент не видит, что специалист внёс чат в ЧС (флаг `isBlocked`
только свой).

---

## 3. Сообщения

### 3.1. Объект сообщения

Одинаковый в истории, ответах на отправку/правку/удаление, `lastMessage` и событиях
`message.new` / `message.updated`.

```json
{
  "id": 1234,
  "channelId": "chat_12_34",
  "senderId": 34,
  "type": "regular",
  "customType": "",
  "text": "Здравствуйте",
  "replyTo": {"id": 1200, "senderId": 12, "text": "Вопрос", "type": "regular"},
  "attachments": [
    {
      "id": "0c4e9b1a-6f0e-4a8b-9a51-1c3a2f6f1e77",
      "kind": "image",
      "fileName": "photo.jpg",
      "mimeType": "image/jpeg",
      "size": 482113,
      "width": 1280,
      "height": 960,
      "durationMs": null,
      "waveform": null,
      "url": "https://files.<DOMAIN>/messenger/chats/77/0c4e…/photo.jpg?X-Amz-Algorithm=...&X-Amz-Signature=..."
    }
  ],
  "call": null,
  "extraData": {},
  "editedAt": null,
  "deletedAt": null,
  "createdAt": "2026-10-26T16:47:36.272523+06:00",
  "clientMsgId": "6f1c2a8e-3b7d-4c55-9f0e-2d9a1b7c4e11"
}
```

| Поле | Описание |
|---|---|
| `type` | `regular` — обычное; `system` — системное (`senderId: null`); `call` — карточка звонка (`senderId` = звонящий, `text: ""`, объект в `call`, см. [CALLS_API.md](CALLS_API.md)) |
| `customType` | у системных: `tariffProvided`, `tariffExpired`, `tariffActivated`, `chatBlocked`; иначе `""` |
| `text` | текст; у удалённого — `""` |
| `replyTo` | краткая копия сообщения, на которое ответили (`text` у удалённого — `""`), или `null` |
| `attachments` | вложения по порядку отправки; у удалённого — `[]` |
| `extraData` | у системных: `{"customType", "clientName", "specialistName"}`; у обычных — `{}`. У перенесённых из GetStream могут быть служебные ключи (`streamUserId`, `streamReplyToId`, `streamAttachments`, `streamType`) — их можно игнорировать |
| `editedAt` | время последней правки или `null` («изменено») |
| `deletedAt` | время удаления или `null`. Удалённое показывайте как «Сообщение удалено» |
| `clientMsgId` | ваш ключ идемпотентности (см. отправку) или `null` |

Вложение (`attachments[]`):

| Поле | Описание |
|---|---|
| `kind` | `image`, `video`, `file`, `voice` |
| `width`, `height`, `durationMs`, `waveform` | метаданные, которые прислал отправитель (могут быть `null`) |
| `url` | ссылка на скачивание, **живёт 1 час**; отдаёт файл с `Content-Disposition: attachment` |

Кэшируйте файлы по `id` вложения (он постоянный), а не по `url`. Если ссылка протухла
(`403` от `files.<DOMAIN>`), перезапросите страницу истории — придут свежие ссылки.

**Перенесённая история.** Старые сообщения из GetStream лежат в той же ленте с исходным
временем. Ответы в тредах GetStream стали обычными сообщениями с `replyTo` на начало треда.
Голосовые из GetStream — `kind: "voice"` с `waveform` в шкале 0–100; аудиофайлы — `kind: "file"`.

### 3.2. История — `GET /api/chats/<channelId>/messages/`

| Параметр | Описание |
|---|---|
| — | последние сообщения, **от новых к старым** |
| `before=<cursor>` | страница старее курсора (листание вверх), от новых к старым |
| `after=<cursor>` | страница новее курсора (догрузка после переподключения), **от старых к новым** |
| `limit` | 1–100, по умолчанию 50 (больше 100 — обрежется до 100) |

```json
{
  "results": [ { "...": "сообщения" } ],
  "hasMore": true,
  "nextCursor": "MjAyNi0xMC0yNlQxMDo0NzozNi4yNzI1MjMrMDA6MDB8MTIzNA"
}
```

- `nextCursor` — курсор **последнего элемента** `results` (`null`, только если `results` пуст).
  Для следующей страницы в том же направлении передайте его в тот же параметр
  (`before` или `after`).
- `hasMore` — есть ли ещё страница в этом направлении.
- Порядок ленты — по (`createdAt`, `id`), не по `id`: перенесённые сообщения могут иметь
  больший `id` при более раннем времени.
- Курсор можно собрать из любого сообщения, которое уже есть в приложении (например,
  пришедшего по WebSocket): base64url **без** `=` от строки `<createdAt>|<id>`, где
  `createdAt` — строка ровно как в JSON сообщения.

```dart
String cursorOf(Map<String, dynamic> m) =>
    base64Url.encode(utf8.encode('${m['createdAt']}|${m['id']}')).replaceAll('=', '');

// догрузка после переподключения: от самого нового известного сообщения
var cursor = cursorOf(newestKnownMessage);
while (true) {
  final page = await api.get('/api/chats/$channelId/messages/', query: {'after': cursor, 'limit': '100'});
  addMessages(page['results']);           // от старых к новым
  if (page['nextCursor'] != null) cursor = page['nextCursor'];
  if (page['hasMore'] != true) break;
}
```

Ошибки: битый курсор, `before` и `after` вместе, `limit` < 1 или не число →
`400 PARAM_INVALID`; не участник → `404 CHAT_NOT_FOUND`. История видна и без тарифа.

### 3.3. Отправка — `POST /api/chats/<channelId>/messages/`

```json
{
  "clientMsgId": "6f1c2a8e-3b7d-4c55-9f0e-2d9a1b7c4e11",
  "text": "Здравствуйте",
  "replyToId": 1200,
  "attachmentIds": ["0c4e9b1a-6f0e-4a8b-9a51-1c3a2f6f1e77"]
}
```

| Поле | Обязательно | Описание |
|---|---|---|
| `clientMsgId` | рекомендуется | UUID, который приложение генерирует **один раз на сообщение** и повторяет при ретраях |
| `text` | нет | до 10 000 символов; пробелы по краям обрезаются |
| `replyToId` | нет | `id` сообщения **этого же** чата |
| `attachmentIds` | нет | вложения, загруженные по разделу 4, в нужном порядке |

Ответ `201` — объект сообщения. Нужен текст или хотя бы одно вложение.

**Идемпотентность.** Повтор с тем же `clientMsgId` (тот же отправитель, тот же чат) вернёт
`201` с **уже созданным** сообщением — без дубля, событий и пушей. Это работает даже если
тариф успел истечь между попытками. Поэтому при обрыве сети смело повторяйте запрос с тем
же `clientMsgId`, а в ленте сопоставляйте локальный «отправляется…» с пришедшим
`message.new` по `clientMsgId`.

После отправки: собеседнику — пуш (раздел 8) и `unreadCount + 1`; обоим — `message.new`;
чат, скрытый любой стороной, снова появляется у обеих.

| Ошибка | Когда |
|---|---|
| `403 TARIFF_REQUIRED` | клиент без активного тарифа |
| `403 VOICE_NOT_ALLOWED` | клиент шлёт голосовое, а специалист запретил (`clientCanSendVoice: false`) |
| `400 MESSAGE_EMPTY` | нет ни текста, ни вложений |
| `400 MESSAGE_NOT_FOUND` | `replyToId` не из этого чата |
| `400 ATTACHMENT_INVALID` | вложение чужое, из другого чата, уже отправлено, повторяется в списке, файл не загружен или его размер вне лимита |
| `400 VALIDATION_ERROR` | неверный формат полей (`errors` — по полям) |
| `404 CHAT_NOT_FOUND` | не участник чата |

### 3.4. Правка — `PATCH /api/chats/<channelId>/messages/<id>/`

```json
{"text": "Исправленный текст"}
```

Только своё **обычное** не удалённое сообщение, без проверки тарифа. Ответ `200` — объект
сообщения (`editedAt` проставлен); обоим — `message.updated`. Пустой текст допустим только
у сообщения с вложениями.

Ошибки: чужое/системное/звонок/удалённое → `403 MESSAGE_EDIT_FORBIDDEN`; пустое без
вложений → `400 MESSAGE_EMPTY`; нет такого сообщения в чате → `404 MESSAGE_NOT_FOUND`.

### 3.5. Удаление — `DELETE /api/chats/<channelId>/messages/<id>/`

Только своё обычное сообщение, мягкое: ответ `200` — объект сообщения с `deletedAt`,
`text: ""`, `attachments: []`; обоим — `message.updated`. Повторное удаление своего — `200`
без изменений. Ошибки — как у правки.

### 3.6. Прочитано — `POST /api/chats/<channelId>/read/`

```json
{"lastReadMessageId": 1234}
```

```json
{"channelId": "chat_12_34", "lastReadMessageId": 1234, "unreadCount": 0}
```

- Отмечает прочитанным всё до этого сообщения включительно; `unreadCount` пересчитывается
  (обычные сообщения собеседника после него).
- Монотонно: сообщение раньше уже прочитанного игнорируется — ответ `200` с текущим
  состоянием.
- Событие `chat.read` уходит собеседнику («прочитано» у его сообщений) и вам
  (синхронизация других ваших устройств).
- Тариф не нужен. Неизвестное сообщение → `404 MESSAGE_NOT_FOUND`.

Вызывайте, когда последнее сообщение собеседника стало видно на экране (не на каждое
сообщение — достаточно последнего видимого).

---

## 4. Вложения, фото, видео, голосовые

Файл идёт **напрямую в хранилище**, мимо API:

1. `POST /api/chats/<channelId>/attachments/` — зарезервировать вложение, получить ссылку.
2. `PUT uploadUrl` — загрузить байты с заголовками `uploadHeaders`.
3. `POST .../messages/` с `attachmentIds: [id]`.

### 4.1. Резерв — `POST /api/chats/<channelId>/attachments/`

```json
{
  "kind": "voice",
  "fileName": "voice.m4a",
  "mimeType": "audio/mp4",
  "size": 48213,
  "durationMs": 7300,
  "waveform": [3, 10, 42, 77, 51, 20]
}
```

| Поле | Обязательно | Описание |
|---|---|---|
| `kind` | да | `image`, `video`, `file`, `voice` |
| `fileName` | да | исходное имя, до 255 символов (покажется получателю и в имени скачанного файла) |
| `mimeType` | да | тип файла; тот же нужно передать в `PUT` |
| `size` | да | размер в байтах, ≥ 1 |
| `width`, `height` | нет | для фото/видео, ≥ 0 |
| `durationMs` | нет | для видео/голосовых, ≥ 0 |
| `waveform` | нет | для голосовых: до 512 целых чисел; рекомендуемая шкала 0–100 (так перенесены голосовые из GetStream) |

Ответ `201`:

```json
{
  "id": "0c4e9b1a-6f0e-4a8b-9a51-1c3a2f6f1e77",
  "uploadUrl": "https://files.<DOMAIN>/messenger/chats/77/0c4e…/voice.m4a?X-Amz-Algorithm=AWS4-HMAC-SHA256&...",
  "uploadHeaders": {"Content-Type": "audio/mp4"},
  "expiresAt": "2026-10-26T17:02:36+06:00"
}
```

Лимиты размера: фото 20 МБ, видео 200 МБ, файл 50 МБ, голосовое 20 МБ (МБ = 1024×1024 байт).

Ошибки: `403 TARIFF_REQUIRED` (клиент без тарифа), `403 VOICE_NOT_ALLOWED` (голосовое
запрещено), `413 ATTACHMENT_TOO_LARGE` (`size` больше лимита), `400 VALIDATION_ERROR`,
`404 CHAT_NOT_FOUND`.

### 4.2. Загрузка

```dart
await dio.put(
  upload['uploadUrl'],
  data: Stream.fromIterable([bytes]),          // или файл потоком
  options: Options(headers: {
    ...Map<String, String>.from(upload['uploadHeaders']),
    Headers.contentLengthHeader: bytes.length,
  }),
);
```

- Ссылка действует **15 минут** (`expiresAt`) и только для `PUT`.
- `Content-Type` обязан совпасть с `uploadHeaders` — он входит в подпись, иначе
  `403 SignatureDoesNotMatch` от хранилища.
- Не добавляйте `Authorization` — доступ даёт сама ссылка.
- Ответ хранилища `200` с пустым телом.

### 4.3. Отправка

`POST .../messages/` с `attachmentIds`. Сервер проверяет, что файл действительно загружен
и его фактический размер в пределах лимита, и только тогда привязывает вложение. Можно
отправить несколько вложений одним сообщением и сообщение только из вложений.
Зарезервированные, но не отправленные вложения удаляются через сутки.

---

## 5. Системные сообщения — `POST /api/chats/<channelId>/system-messages/`

Замена `POST /api/stream/send-system-message/`: вызывайте в тех же местах, где старое
приложение вызывало старый эндпоинт. Доступно любому участнику чата, тариф не нужен.

```json
{"customType": "tariffActivated", "text": "Тариф активирован."}
```

| `customType` | Текст по умолчанию |
|---|---|
| `tariffProvided` | Доступ по тарифу предоставлен. |
| `tariffExpired` | Срок действия тарифа истёк. |
| `tariffActivated` | Тариф активирован. |
| `chatBlocked` | Чат заблокирован. |

`text` необязателен (до 10 000 символов). Ответ `200`:

```json
{"success": true, "clientName": "Иван Иванов", "specialistName": "Анна Петрова"}
```

`success: false` — сообщение такого же типа уже было в этом чате за последние 10 минут
(дубль не создаётся). Созданное сообщение (`type: "system"`, `senderId: null`) приходит
обоим как `message.new`; пушей и `unreadCount` не даёт.

Ошибки: неизвестный `customType` → `400 VALIDATION_ERROR`; не участник → `404 CHAT_NOT_FOUND`.

---

## 6. Тариф: что можно без него

«Активный тариф» — у чата есть оплаченный доступ с `expiresAt` в будущем
(в списке чатов: `tariff != null && tariff.expiresAt > now`).

| Действие | Клиент с тарифом | Клиент без тарифа | Специалист |
|---|---|---|---|
| Читать историю, отмечать прочитанным | да | да | да |
| Писать текст, слать вложения | да | `TARIFF_REQUIRED` | всегда |
| Голосовые | если `clientCanSendVoice` (иначе `VOICE_NOT_ALLOWED`) | `TARIFF_REQUIRED` | всегда |
| Править и удалять свои сообщения | да | да | да |
| Системные сообщения | да | да | да |
| Начать / принять звонок | да | `TARIFF_REQUIRED` | только при активном тарифе чата |

Истёкший во время звонка тариф звонок не обрывает. Приветствие специалиста приходит всегда.
Решение принимает сервер — проверка в приложении нужна только чтобы заранее показать
правильный UI.

---

## 7. События личного канала

Конверт `{"type", "data"}`; `data` в camelCase, как в REST.

| `type` | Кому | `data` | Когда |
|---|---|---|---|
| `message.new` | обоим | объект сообщения | новое обычное/системное сообщение, приветствие, карточка звонка |
| `message.updated` | обоим | объект сообщения | правка, удаление, смена статуса звонка в карточке |
| `chat.read` | обоим | `{channelId, userId, lastReadMessageId}` | `userId` прочитал до `lastReadMessageId` |
| `chat.updated` | каждому свой | см. ниже | заметка, `clientCanSendVoice`, избранное, ЧС, оплата/активация тарифа |
| `chat.user_updated` | собеседникам пользователя | см. ниже | собеседник изменил профиль, график, нерабочие даты |
| `call.incoming` | вызываемому | `{call, caller: {id, name}}` | входящий звонок |
| `call.accepted`, `call.declined`, `call.cancelled`, `call.ended`, `call.missed` | обоим | `{call}` | смена статуса звонка ([CALLS_API.md](CALLS_API.md)) |

Обработка `message.new` / `message.updated`: вставить или заменить сообщение по `id`
(для своих — сопоставить по `clientMsgId`), обновить `lastMessage` и порядок чата в списке.
`unreadCount` событие не содержит: увеличивайте его сами на `message.new` от собеседника
с `type: "regular"` в неоткрытом чате, а точное значение берите из `GET /api/chats/`.

`chat.read`:

```json
{"type": "chat.read", "data": {"channelId": "chat_12_34", "userId": 34, "lastReadMessageId": 1234}}
```

`userId` — собеседник → пометить свои сообщения до `lastReadMessageId` (по порядку ленты)
прочитанными; `userId` — вы → обнулить счётчик на этом устройстве.

`chat.updated` (у каждого участника свои `isFavorite`/`isBlocked`; `specialistNote` есть
**только** в событии специалисту — у клиента ключа нет):

```json
{
  "type": "chat.updated",
  "data": {
    "channelId": "chat_12_34",
    "clientCanSendVoice": true,
    "tariff": {"name": "Месяц", "activatedAt": "2026-10-26T15:00:00+06:00", "expiresAt": "2026-11-25T15:00:00+06:00"},
    "isFavorite": true,
    "isBlocked": false,
    "specialistNote": "заметка"
  }
}
```

Значения те же, что в `GET /api/chats/` (`tariff: null`, если оплат не было).

`chat.user_updated` (замена `user_update` из `ws/chats/`):

```json
{
  "type": "chat.user_updated",
  "data": {
    "user": { "id": 34, "firstName": "Анна", "lastName": "Петрова", "photo": "...", "canAudioCall": true, "canVideoCall": true, "...": "как GET /api/users/me/" },
    "changes": ["first_name", "photo"],
    "schedule": [ { "...": "как /api/work-schedules/" } ],
    "nonWorkingDates": [ {"id": 12, "date": "2026-10-05"} ]
  }
}
```

`changes` — имена изменённых полей **в snake_case** (как в старом `user_update`):
поля профиля, `"schedule"` или `"non_working_dates"`.

---

## 8. Пуш о новом сообщении (FCM)

Отправляется получателю на каждое новое **обычное** сообщение собеседника (не системное,
не звонок). Не отправляется, если получатель внёс чат в чёрный список. **В ленту
уведомлений не пишется** (в отличие от остальных пушей, см.
[FLUTTER_NOTIFICATIONS.md](FLUTTER_NOTIFICATIONS.md)) и не содержит `source`.

- `notification.title` — имя отправителя, `body` — текст или «Фото» / «Видео» / «Файл» /
  «Голосовое сообщение» (по первому вложению).
- Android: `tag = channelId` — новое уведомление чата заменяет предыдущее.
  iOS: `thread-id = channelId` — уведомления чата группируются.
- `data` (все значения строки):

```json
{"type": "chat_message", "channelId": "chat_12_34", "messageId": "1234", "senderId": "34", "senderName": "Анна Петрова"}
```

По нажатию — открыть чат `channelId`. Если чат уже открыт и сокет подключён, пуш можно не
показывать.

Пуши о звонках (`incoming_call`, `missed_call`) — в [CALLS_API.md](CALLS_API.md).

---

## 9. Ошибки мессенджера

| Код | HTTP | Где | Что делать приложению |
|---|---|---|---|
| `TARIFF_REQUIRED` | 403 | отправка, вложения, звонки | показать экран покупки/продления тарифа |
| `VOICE_NOT_ALLOWED` | 403 | голосовое | скрыть запись голосового, показать `message` |
| `MESSAGE_EMPTY` | 400 | отправка, правка | не отправлять пустое |
| `MESSAGE_NOT_FOUND` | 404 / 400 | правка, удаление, прочитано (404); `replyToId` (400) | обновить ленту |
| `MESSAGE_EDIT_FORBIDDEN` | 403 | правка, удаление | не показывать действие для чужих/системных |
| `ATTACHMENT_INVALID` | 400 | отправка с вложениями | загрузить файл заново (новый резерв) |
| `ATTACHMENT_TOO_LARGE` | 413 | резерв вложения | показать лимит |
| `CHAT_NOT_FOUND` | 404 | всё под `chats/<channelId>/` | чата нет или вы не участник |
| `PARAM_INVALID` | 400 | история (`before`/`after`/`limit`) | сбросить курсор, загрузить с начала |
| `REALTIME_UNAVAILABLE` | 503 | токены Centrifugo, звонки | повторить позже |
| `VALIDATION_ERROR` | 400 | любые тела запросов | ошибки по полям в `errors` |

Коды звонков (`CALL_*`) — в [CALLS_API.md](CALLS_API.md). Полный список —
[API_ERROR_CODES.md](API_ERROR_CODES.md).

---

## 10. Что заменить из GetStream SDK

| Было (GetStream) | Стало |
|---|---|
| `streamToken` из логина / `GET /api/auth/stream-token/`, `StreamChatClient.connectUser` | `GET /api/messenger/connection-token/` + `centrifuge` (раздел 1). `streamToken` новое приложение не использует (поле уберут после переключения) |
| `client.queryChannels` | `GET /api/chats/` |
| `channel.watch()`, `channel.state.messages` | `GET .../messages/` + события `message.new` / `message.updated` |
| `channel.query(messagesPagination: lessThan)` | `?before=<nextCursor>` |
| Переподключение и догрузка в SDK | `connected` → `GET /api/chats/` + `?after=<cursor>` (раздел 1.5) |
| `channel.sendMessage(Message(text, quotedMessageId))` | `POST .../messages/` `{clientMsgId, text, replyToId}` |
| `channel.sendImage/sendFile`, `Attachment(type: 'voiceRecording')` | резерв → `PUT` → `attachmentIds` (раздел 4) |
| `client.updateMessage` / `client.deleteMessage` | `PATCH` / `DELETE .../messages/<id>/` |
| Треды (`parentId`, `channel.getReplies`) | нет; ответ — `replyToId` (перенесённые треды стали ответами) |
| `channel.markRead()`, `channel.state.unreadCount`, `read` других участников | `POST .../read/`, `unreadCount` в списке, событие `chat.read` |
| `channel.keyStroke()` / `typing.start` | публикация `{"type":"typing"}` в `chat:<channelId>` (раздел 1.4) |
| `watcherCount`, `user.online` | presence/join/leave канала `chat:<channelId>` |
| `channel.extraData`: `tariffName`, `activatedAt`, `expiresAt` | `tariff {name, activatedAt, expiresAt}` в списке и `chat.updated` |
| `channel.extraData`: `favoriteBy`, `blockedBy`, `specialist_note` | `isFavorite`, `isBlocked` (свои), `specialistNote` (специалисту) |
| `channel.mute()` / `client.muteUser` | ничего: ЧС на сервере сам отключает пуши |
| `channel.hide()` / `show` | `POST /api/chats/soft-delete/`; новое сообщение показывает чат обратно само |
| Системные сообщения `POST /api/stream/send-system-message/` | `POST /api/chats/<channelId>/system-messages/` (раздел 5) |
| Пуши Stream о сообщениях | FCM `type: chat_message` (раздел 8) |
| `ws/chats/<channelId>/` (`user_update`) | событие `chat.user_updated` в личном канале |
| Звонки Stream Video | [CALLS_API.md](CALLS_API.md) |
| Реакции, закрепы, пересылка, поиск | пока нет (будут, если понадобятся) |

Чек-лист перехода:

- [ ] Убрать зависимости `stream_chat_flutter*`, инициализацию Stream и `streamToken`.
- [ ] Подключение к Centrifugo после логина, отключение при выходе; обработчик всех типов из раздела 7.
- [ ] Список чатов из `GET /api/chats/`, сортировка по `lastMessageAt`, бейджи из `unreadCount`, «нужно ответить» из `shouldReply`.
- [ ] Экран чата: история с курсорами, отправка с `clientMsgId` и ретраями, правка, удаление, ответ на сообщение.
- [ ] Вложения и голосовые через резерв + `PUT`; кэш файлов по `id` вложения.
- [ ] Прочитано: `POST .../read/` при показе последнего сообщения, галочки по `chat.read`.
- [ ] «Печатает…» и «в чате» через канал `chat:<channelId>`.
- [ ] Тариф: доступность ввода по `tariff.expiresAt`, обработка `TARIFF_REQUIRED` / `VOICE_NOT_ALLOWED`.
- [ ] Системные сообщения через новый эндпоинт; рендер `type: system` по `customType`.
- [ ] Пуши `chat_message` (открыть чат) и звонки по [CALLS_API.md](CALLS_API.md).
- [ ] Догрузка после переподключения и выхода из фона (раздел 1.5).
