# Звонки: API для Flutter (LiveKit)

Аудио- и видеозвонки 1:1 внутри чата. Сигналинг и медиа — LiveKit на нашем сервере,
управление звонком (кто кому звонит, принят ли, сколько длился) — REST нашего бэкенда,
уведомления — события Centrifugo (см. [MESSENGER_API.md](MESSENGER_API.md), раздел 1) и
пуши: iOS — VoIP (PushKit → CallKit), Android — FCM data-only.

Пакеты: [`livekit_client`](https://pub.dev/packages/livekit_client) (медиа),
[`flutter_callkit_incoming`](https://pub.dev/packages/flutter_callkit_incoming)
(системный экран входящего звонка, PushKit-токен на iOS),
[`firebase_messaging`](https://pub.dev/packages/firebase_messaging) (Android).

Все запросы авторизованные (Bearer), camelCase, ошибки — с `code`
([API_ERROR_CODES.md](API_ERROR_CODES.md)).

## 1. Объект звонка

```json
{
  "id": "5b1f0c7e-2a3d-4e5f-8a9b-0c1d2e3f4a5b",
  "channelId": "chat_12_34",
  "callerId": 12,
  "calleeId": 34,
  "kind": "video",
  "status": "ended",
  "createdAt": "2026-10-26T16:00:00.000000+06:00",
  "answeredAt": "2026-10-26T16:00:07.000000+06:00",
  "endedAt": "2026-10-26T16:12:31.000000+06:00",
  "durationSeconds": 744,
  "endReason": "hangup"
}
```

| Поле | Описание |
|---|---|
| `kind` | `audio` / `video` |
| `status` | см. таблицу ниже |
| `answeredAt` | когда принят (`null`, если не принимали) |
| `endedAt` | когда завершён (`null`, пока звонок идёт) |
| `durationSeconds` | длительность разговора от ответа до конца; `0`, если не было разговора |
| `endReason` | почему завершён: `""` (идёт), `busy`, `declined`, `cancelled`, `timeout`, `hangup`, `disconnected`, `max_duration` |

| `status` | Значит | Конечный |
|---|---|---|
| `ringing` | идёт вызов | нет |
| `accepted` | идёт разговор | нет |
| `busy` | у кого-то из двоих уже шёл звонок — вызов не состоялся | да |
| `declined` | вызываемый отклонил | да |
| `cancelled` | звонящий отменил до ответа | да |
| `missed` | никто не ответил за 45 с | да |
| `ended` | разговор завершён | да |
| `failed` | зарезервирован, сейчас сервер его не выставляет | да |

Каждый звонок — ещё и **карточка в ленте чата**: сообщение `type: "call"`, `senderId` =
звонящий, `text: ""`, объект звонка в поле `call`. Она приходит `message.new` при старте и
`message.updated` при каждой смене статуса; бывает `lastMessage` в списке чатов; не
увеличивает `unreadCount` и не даёт пуша о сообщении.

## 2. Состояния

```
POST chats/<channelId>/calls/
  ├─ у звонящего или вызываемого уже идёт звонок ──► busy (сразу, token = null)
  ▼
ringing ──decline/ (вызываемый) или end/ (вызываемый)──► declined  endReason=declined
   │    ──cancel/ (звонящий) или end/ (звонящий)──────► cancelled endReason=cancelled
   │    ──45 с без ответа────────────────────────────► missed    endReason=timeout (+ пуш «Пропущенный звонок»)
   │
 accept/ (вызываемый)
   ▼
accepted ──end/ (любой участник)──────────────────────► ended  endReason=hangup
         ──в комнате никого не осталось / закрыта──────► ended  endReason=disconnected
         ──дольше 2 часов──────────────────────────────► ended  endReason=max_duration
```

Любое другое действие → `409 CALL_INVALID_STATE` (например, `accept/` уже отменённого).

Правила:

- **Тариф.** Начать звонок можно только при активном тарифе чата — и клиенту, и
  специалисту; принять — тоже. Истечение тарифа во время разговора звонок не обрывает.
  Иначе → `403 TARIFF_REQUIRED`.
- **Чёрный список.** Если вызываемый внёс чат в ЧС → `403 CALL_NOT_ALLOWED`.
- **Флаги вызываемого `canAudioCall` / `canVideoCall`** (профиль, `/api/users/me/can-call/`).
  Если вызываемый отключил этот тип звонков (`kind=audio` → `canAudioCall`, `kind=video` →
  `canVideoCall`) → `403 CALL_NOT_ALLOWED`; звонок и сообщение о нём не создаются (даже если
  вызываемый сейчас занят). Кнопки звонка приложение по-прежнему скрывает само — проверка
  сервера на случай устаревшего профиля.
- **Занято.** Если у звонящего или вызываемого есть идущий звонок (`ringing` не старше
  ~60 с или `accepted` не дольше 2 ч) — звонок создаётся сразу в статусе `busy`.
- **Таймаут вызова** — 45 с. Вызов, который «завис» дольше 60 с, принять уже нельзя:
  `accept/` вернёт `409 CALL_INVALID_STATE`, а звонок станет `missed`.
- **Разрыв.** Сервер сам завершает принятый звонок (`ended`, `disconnected`), даже если
  `end/` никто не прислал, когда в комнате LiveKit **никого не осталось** (оба вышли или
  потеряли сеть дольше, чем SDK успевает переподключиться) или комната закрылась. Если вышел
  только один участник, а второй ещё в комнате, звонок **не** завершается (короткий обрыв сети
  у одного не рвёт разговор) — оставшийся участник видит `ParticipantDisconnectedEvent` и сам
  решает, когда нажать «Завершить» (`end/`, см. 6.3). Если сигнал от LiveKit потерялся — не
  позже чем через ~60 с после исчезновения комнаты.

## 3. REST

### 3.1. Начать — `POST /api/chats/<channelId>/calls/`

```json
{"kind": "video"}
```

`kind` — `audio` (по умолчанию) или `video`. Ответ `201`:

```json
{
  "call": { "...": "объект звонка, status = ringing" },
  "livekitUrl": "wss://rtc.<DOMAIN>",
  "token": "eyJhbGciOiJIUzI1NiIs..."
}
```

Если `call.status == "busy"` — `token: null`, показать «Абонент занят» (это не ошибка).

Ошибки: `403 TARIFF_REQUIRED`, `403 CALL_NOT_ALLOWED` (ЧС или у вызываемого выключен
`canAudioCall` / `canVideoCall` для этого `kind`), `404 CHAT_NOT_FOUND`,
`400 VALIDATION_ERROR` (неверный `kind`), `503 REALTIME_UNAVAILABLE` (LiveKit недоступен —
звонок не создан, можно повторить).

### 3.2. Принять — `POST /api/calls/<callId>/accept/`

Только вызываемый. Ответ `200` — такой же `{call, livekitUrl, token}` (`status: accepted`).

Ошибки: `403 CALL_NOT_ALLOWED` (принимает не вызываемый), `403 TARIFF_REQUIRED`,
`404 CALL_NOT_FOUND`, `409 CALL_INVALID_STATE` (звонок уже не звонит — отменён, пропущен,
принят с другого устройства), `503 REALTIME_UNAVAILABLE`.

### 3.3. Отклонить / отменить / завершить

| Запрос | Кто | Из какого статуса | Результат |
|---|---|---|---|
| `POST /api/calls/<callId>/decline/` | вызываемый | `ringing` | `declined` |
| `POST /api/calls/<callId>/cancel/` | звонящий | `ringing` | `cancelled` |
| `POST /api/calls/<callId>/end/` | любой участник | `accepted` → `ended`; `ringing` → `cancelled` (звонящий) / `declined` (вызываемый) | |

Ответ `200` — объект звонка (без обёртки). Ошибки: `403 CALL_NOT_ALLOWED` (decline от
звонящего, cancel от вызываемого), `404 CALL_NOT_FOUND`, `409 CALL_INVALID_STATE` (звонок
уже завершён — просто закройте экран). Тариф для завершения не нужен.

Достаточно всегда слать `end/` на кнопку «положить трубку» — сервер сам выберет итог.

### 3.4. Звонок по id — `GET /api/calls/<callId>/`

Объект звонка; не участник → `404 CALL_NOT_FOUND`. Полезно, чтобы проверить актуальность
пуша о входящем звонке.

### 3.5. Текущий звонок — `GET /api/calls/active/`

Для восстановления после перезапуска приложения (упало, убито системой, открыто из пуша).
Всегда `200`:

```json
{"call": { "...": "объект звонка" }, "livekitUrl": "wss://rtc.<DOMAIN>", "token": "eyJ..."}
```

```json
{"call": null, "livekitUrl": "wss://rtc.<DOMAIN>", "token": null}
```

- `call` — ваш идущий звонок (`ringing` не старше ~60 с или `accepted` не дольше 2 ч) или `null`.
- `token` для `accepted` — обоим участникам (вернуться в разговор); для `ringing` — только
  звонящему; вызываемому — `null`: показать входящий звонок и принять через `accept/`.

## 4. События (личный канал Centrifugo)

| `type` | Кому | `data` |
|---|---|---|
| `call.incoming` | вызываемому | `{call, caller: {id, name}}` |
| `call.accepted` | обоим | `{call}` |
| `call.declined` | обоим | `{call}` |
| `call.cancelled` | обоим | `{call}` |
| `call.missed` | обоим | `{call}` |
| `call.ended` | обоим | `{call}` |
| `message.new` / `message.updated` | обоим | карточка звонка (`type: "call"`) |

```json
{
  "type": "call.incoming",
  "data": {
    "call": {"id": "5b1f…", "channelId": "chat_12_34", "callerId": 12, "calleeId": 34, "kind": "video", "status": "ringing", "...": "..."},
    "caller": {"id": 12, "name": "Иван Иванов"}
  }
}
```

Для `busy` событий `call.*` нет: звонящий узнаёт из ответа на старт, обоим приходит
карточка `message.new` со статусом `busy`.

События приходят на **все** устройства участника: если звонок принят или отклонён на одном
устройстве, на остальных по `call.accepted` / `call.declined` / … закройте экран входящего
(`FlutterCallkitIncoming.endCall(callId)`).

## 5. Пуши

### 5.1. iOS — VoIP (PushKit)

APNs `apns-push-type: voip`, topic `<bundleId>.voip`, priority 10, живёт 45 с. Отправляется
на все зарегистрированные VoIP-токены вызываемого, пока звонок ещё `ringing`.
`payload.dictionaryPayload` (без `aps`):

```json
{"type": "incoming_call", "callId": "5b1f…", "channelId": "chat_12_34", "kind": "video", "callerId": 12, "callerName": "Иван Иванов"}
```

`callerId` здесь число.

**iOS требует на каждый VoIP-пуш сразу показать CallKit**, иначе система перестанет
доставлять VoIP-пуши приложению. Поэтому показывайте CallKit всегда, а уже потом
проверяйте `GET /api/calls/<callId>/`: если статус не `ringing` — сразу
`FlutterCallkitIncoming.endCall(callId)`.

Показ — нативно в `AppDelegate.swift` (Flutter может быть не запущен):

```swift
import PushKit
import flutter_callkit_incoming

func pushRegistry(_ registry: PKPushRegistry,
                  didReceiveIncomingPushWith payload: PKPushPayload,
                  for type: PKPushType, completion: @escaping () -> Void) {
    guard type == .voIP else { return }
    let p = payload.dictionaryPayload
    let callId = p["callId"] as? String ?? UUID().uuidString
    let name = p["callerName"] as? String ?? ""
    let data = flutter_callkit_incoming.Data(id: callId, nameCaller: name, handle: name,
                                             type: (p["kind"] as? String) == "video" ? 1 : 0)
    data.duration = 45000
    data.extra = ["callId": callId, "channelId": p["channelId"] ?? "", "kind": p["kind"] ?? "audio"]
    SwiftFlutterCallkitIncomingPlugin.sharedInstance?.showCallkitIncoming(data, fromPushKit: true)
    completion()
}

func pushRegistry(_ registry: PKPushRegistry, didUpdate credentials: PKPushCredentials, for type: PKPushType) {
    let token = credentials.token.map { String(format: "%02x", $0) }.joined()
    SwiftFlutterCallkitIncomingPlugin.sharedInstance?.setDevicePushTokenVoIP(token)
}
```

`callId` — UUID, его же используйте как id CallKit-звонка.

### 5.2. Регистрация VoIP-токена (iOS)

```
POST /api/messenger/voip-devices/
```

```json
{"token": "a1b2c3…(hex PushKit-токен)", "bundleId": "kg.profichat.app"}
```

Ответ `201` (новый токен) или `200` (уже был) — `{"token", "bundleId", "active": true}`.

- Вызывайте после логина и при каждом запуске (идемпотентно): токен перепривязывается к
  текущему пользователю и снова становится активным.
- Токен из Dart: `await FlutterCallkitIncoming.getDevicePushTokenVoIP()`, обновления —
  событие `Event.actionDidUpdateDevicePushTokenVoip`.
- При выходе из аккаунта: `DELETE /api/messenger/voip-devices/<token>/` → `204`
  (идемпотентно, чужой токен не трогается).
- Токен, который APNs отверг как недействительный, сервер выключает сам.
- `bundleId` сохраняется для справки; topic берётся из настройки сервера (`APNS_BUNDLE_ID`).
- Сборки из Xcode (debug) получают sandbox-токены — они работают только с сервером, где
  `APNS_USE_SANDBOX=True` (staging). TestFlight и App Store — с боевым.

### 5.3. Android — FCM data-only

Те же ключи, все значения строки (`"callerId": "12"`), без блока `notification`,
`android.priority = high`, TTL 45 с. Уходит на все FCM-устройства вызываемого.

```dart
@pragma('vm:entry-point')
Future<void> firebaseMessagingBackgroundHandler(RemoteMessage message) async {
  final d = message.data;
  if (d['type'] != 'incoming_call') return;
  await FlutterCallkitIncoming.showCallkitIncoming(CallKitParams(
    id: d['callId'],
    nameCaller: d['callerName'],
    appName: 'ProfiChat',
    type: d['kind'] == 'video' ? 1 : 0,
    duration: 45000,
    extra: Map<String, dynamic>.from(d),
    android: const AndroidParams(isCustomNotification: true, isShowFullLockedScreen: true),
  ));
}
```

> ⚠️ **iOS-устройства тоже получат этот FCM data-only `incoming_call`**: сервер не знает
> платформу FCM-токена и шлёт его на все устройства. На iOS такой пуш доходит только в
> foreground и **должен игнорироваться** — входящий звонок на iOS показывается только
> из VoIP-пуша (и `call.incoming`, если VoIP не зарегистрирован).

### 5.4. Пропущенный звонок

Когда вызов уходит в `missed`, вызываемому приходит обычный пуш и запись в ленте
уведомлений (кроме случая, когда он внёс чат в ЧС):

- заголовок «Пропущенный звонок», текст «Звонок от Иван Иванов» или «Видеозвонок от …»;
- `type: "missed_call"`, `source: "profichat"`;
- `payload`/`data`: `{"callId", "channelId", "kind", "callerId", "callerName", "type", "source"}`
  (в FCM — строки).

По нажатию — открыть чат `channelId`.

## 6. Сценарии

### 6.1. Звонящий

1. `POST /api/chats/<channelId>/calls/` `{kind}`.
2. `status == busy` → «Абонент занят», конец.
3. Сразу подключиться к комнате с полученным `token` и включить микрофон (и камеру для
   видео); экран «Вызов…».
4. Ждать событие: `call.accepted` → «Разговор»; `call.declined` / `call.missed` /
   `call.cancelled` → отключиться от комнаты, закрыть экран с соответствующим текстом.
5. «Отмена» до ответа или «Положить трубку» — `POST /api/calls/<id>/end/`, затем
   `room.disconnect()`.
6. `call.ended` от собеседника → `room.disconnect()`, закрыть экран.

### 6.2. Вызываемый

1. Входящий: `call.incoming` (приложение открыто), VoIP-пуш (iOS) или FCM `incoming_call`
   (Android). Это может быть один и тот же звонок из двух источников — **сравнивайте по
   `callId`** и показывайте один экран.
2. «Принять» → `POST /api/calls/<id>/accept/` → подключиться к комнате с `token`.
   `409 CALL_INVALID_STATE` → звонок уже не актуален, закрыть экран.
3. «Отклонить» → `POST /api/calls/<id>/decline/`.
4. События `call.cancelled` / `call.missed` / `call.accepted` (с другого вашего устройства)
   → закрыть экран входящего.

```dart
FlutterCallkitIncoming.onEvent.listen((CallEvent? event) async {
  final callId = event?.body['id'] as String?;
  if (callId == null) return;
  switch (event!.event) {
    case Event.actionCallAccept:
      final session = await api.post('/api/calls/$callId/accept/');
      await joinRoom(session['livekitUrl'], session['token'], session['call']['kind'] == 'video');
      break;
    case Event.actionCallDecline:
      await api.post('/api/calls/$callId/decline/');
      break;
    case Event.actionCallEnded:
      await api.post('/api/calls/$callId/end/');
      break;
    default:
      break;
  }
});
```

### 6.3. Подключение к комнате (`livekit_client`)

```dart
Future<Room> joinRoom(String url, String token, bool video) async {
  final room = Room();
  room.createListener()
    ..on<RoomDisconnectedEvent>((_) => closeCallScreen())
    ..on<ParticipantDisconnectedEvent>((e) => showReconnectingOrEnd(e.participant.identity));
  await room.connect(url, token);
  await room.localParticipant?.setMicrophoneEnabled(true);
  if (video) await room.localParticipant?.setCameraEnabled(true);
  return room;
}
```

- Комната — `call_<callId>`, максимум 2 участника; `identity` участника = id пользователя
  строкой, `name` — имя и фамилия.
- Токен действует 2 часа. Права: аудиозвонок — только микрофон, видеозвонок — микрофон и
  камера; демонстрация экрана недоступна. **Перейти из аудио в видео в том же звонке нельзя**
  (камеру токен аудиозвонка не разрешает) — нужен новый видеозвонок.
- TURN/TLS на 443 (`turns:turn.<DOMAIN>:443`) SDK получает от сервера сам — ничего
  настраивать не нужно; это для сетей, где закрыт UDP.
- После завершения звонка сервер закрывает комнату — SDK получит `RoomDisconnectedEvent`.
- `ParticipantDisconnectedEvent` (собеседник пропал) звонок на сервере **не** завершает, пока
  вы в комнате: покажите «Переподключение…» и, если собеседник не вернулся за разумное время
  (например, 30 с), завершите звонок сами — `POST /api/calls/<callId>/end/`.
- Комнату создаёт только сервер при старте звонка; войти по токену в закрытую комнату
  завершённого звонка нельзя (LiveKit `room.auto_create: false`).

### 6.4. Перезапуск приложения

При старте (и при открытии из пуша) — `GET /api/calls/active/`:

- `call == null` — ничего не идёт;
- `accepted` + `token` — вернуть пользователя в разговор (подключиться к комнате);
- `ringing`, вы звонящий, есть `token` — снова экран «Вызов…»;
- `ringing`, вы вызываемый, `token: null` — экран входящего, дальше `accept/` / `decline/`.

## 7. Ошибки звонков

| Код | HTTP | Когда | Что делать |
|---|---|---|---|
| `TARIFF_REQUIRED` | 403 | старт/приём без активного тарифа | экран тарифа |
| `CALL_NOT_ALLOWED` | 403 | вызываемый внёс чат в ЧС или отключил этот тип звонков (`canAudioCall` / `canVideoCall`); действие не по роли (принять/отклонить — звонящим, отменить — вызываемым) | показать `message` |
| `CALL_NOT_FOUND` | 404 | нет такого звонка или вы не участник | закрыть экран |
| `CALL_INVALID_STATE` | 409 | действие не подходит к текущему статусу (уже принят, отменён, пропущен, завершён) | закрыть экран, при необходимости `GET /api/calls/<id>/` |
| `REALTIME_UNAVAILABLE` | 503 | LiveKit недоступен | «Не удалось позвонить, попробуйте позже» |
| `CHAT_NOT_FOUND` | 404 | старт в чужом/несуществующем чате | — |
