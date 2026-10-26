# Переход с GetStream на свой мессенджер — runbook

Порядок действий для бэкенда/DevOps. API для приложения — [MESSENGER_API.md](MESSENGER_API.md)
и [CALLS_API.md](CALLS_API.md). Дизайн — `docs/superpowers/specs/2026-10-25-own-messenger-design.md`.

Короткая схема:

```
A. Staging: копия прода → обязательный dry-run по каналам → полный импорт → тесты Flutter
B. Прод:   деплой бэкенда (старое приложение работает как раньше) → полный импорт
C. Окно:   релиз приложения + принудительное обновление → дельта --since → ФИНАЛЬНЫЙ полный
           прогон без --since → сверка по каналам
D. Потом:  GetStream больше не источник → уборка кода (§9 спеки) → только после её деплоя
           отключить аккаунт и ключи GetStream
```

Двусторонней синхронизации со Stream нет. До включения принудительного обновления всё
обратимо (новый бэкенд совместим со старым приложением). **После** — нет: сообщения из
нового приложения в Stream не попадают, откат на старое приложение их потеряет.

---

## 0. Что нужно до начала

### 0.1. DNS

A-записи на тот же сервер, что и `<DOMAIN>`: `files.<DOMAIN>` (вложения, MinIO),
`rtc.<DOMAIN>` (сигналинг звонков, LiveKit), `turn.<DOMAIN>` (TURN/TLS на 443).
Сертификат один на все четыре имени — certbot выпустит его при старте nginx
(`GET_CERTS=True`), **только если все записи уже резолвятся**. Иначе в логе nginx
`[certbot] не удалось получить сертификат…`, старый сертификат на `<DOMAIN>` продолжит
работать, а поддомены по https — нет. Исправить DNS и перезапустить nginx.

### 0.2. Порты и фаервол

| Порт | Открыт наружу | Кто |
|---|---|---|
| 80/tcp, 443/tcp | да | nginx (443: https и TURN/TLS по SNI) |
| 7881/tcp | да | LiveKit, WebRTC по TCP |
| 7882/udp | да | LiveKit, медиа (один UDP-порт) |
| 3478/udp | да | LiveKit TURN/UDP |
| 7880/tcp, 5349/tcp | **нет** — только из docker-сетей | LiveKit API/сигналинг и TURN-слушатель; снаружи доступны через nginx (`rtc.`, `turn.`) |
| 9000, 9001, 6379 | нет (слушают 127.0.0.1) | MinIO, Redis |

LiveKit работает в `network_mode: host`, поэтому nginx, backend и celery ходят к нему через
`host.docker.internal` (шлюз docker). Если на сервере включён `ufw`, разрешите это явно:

```bash
ufw allow 80,443/tcp
ufw allow 7881/tcp
ufw allow 7882/udp
ufw allow 3478/udp
ufw allow from 172.16.0.0/12 to any port 7880,5349 proto tcp   # docker-сети → LiveKit
```

### 0.3. Переменные `.env.prod`

Полный список с комментариями — `.env.example`. Новые:

| Переменная | Значение в проде |
|---|---|
| `CENTRIFUGO_API_URL` | `http://centrifugo:8000/api` |
| `CENTRIFUGO_API_KEY`, `CENTRIFUGO_TOKEN_SECRET` | `openssl rand -hex 32` (разные) |
| `CENTRIFUGO_WS_URL` | `wss://<DOMAIN>/connection/websocket` |
| `S3_ENDPOINT_URL` | `http://minio:9000` |
| `S3_PUBLIC_ENDPOINT_URL` | `https://files.<DOMAIN>` |
| `S3_ACCESS_KEY`, `S3_SECRET_KEY` | логин/пароль MinIO (пароль ≥ 8 символов) |
| `S3_BUCKET`, `S3_REGION` | `messenger`, `us-east-1` |
| `S3_KMS_SECRET_KEY` | `messenger-key:$(openssl rand -base64 32)` |
| `LIVEKIT_URL` | `wss://rtc.<DOMAIN>` |
| `LIVEKIT_API_URL` | `http://host.docker.internal:7880` |
| `LIVEKIT_API_KEY`, `LIVEKIT_API_SECRET` | ключ — любая строка, секрет ≥ 32 символов |
| `LIVEKIT_TURN_DOMAIN` | `turn.<DOMAIN>` (обязателен, без него livekit не стартует) |
| `LIVEKIT_WEBHOOK_URL` | `https://<DOMAIN>/api/messenger/livekit-webhook/` |
| `APNS_KEY_PATH`, `APNS_KEY_ID`, `APNS_TEAM_ID`, `APNS_BUNDLE_ID`, `APNS_USE_SANDBOX` | .p8-ключ APNs для VoIP-пушей; путь — внутри контейнера, например `/app/secrets/AuthKey_XXXX.p8` (файл `app/secrets/…` на сервере, в git не коммитить) |

> ⚠️ **`S3_KMS_SECRET_KEY` терять и менять нельзя**: все файлы в MinIO зашифрованы им
> (SSE-S3). Сохраните его в хранилище секретов вместе с бэкапом тома `minio-data`.

Пустые значения в `.env` пишите без комментария в той же строке: docker compose прочитает
`KEY=   # текст` как значение `# текст`.

### 0.4. Место на диске

Импорт скачивает все вложения из GetStream в MinIO (том `minio-data`). Оцените объём по
статистике хранилища в панели GetStream и оставьте запас ×1.5.

---

## A. Staging (обязательно до прода)

Цель — прогнать импорт на копии боевых данных и дать Flutter-разработчику тестировать новое
приложение, **не отправляя ничего реальным людям** и не трогая боевой GetStream.

### A1. Сервер и `.env.staging`

Отдельный сервер (прод-compose занимает 80/443 и порты LiveKit в сети хоста) со своим
доменом, например `staging.<DOMAIN>` и записями `files.`/`rtc.`/`turn.staging.<DOMAIN>`.
Конфиг — `.env.staging` по образцу `.env.example` (п. 0.3 с доменом staging); на сервере
staging он копируется в `.env.prod`, который читает `docker-compose.prod.yml`:

```bash
cp .env.staging .env.prod
```

Обязательно в `.env.staging`:

- `STREAM_API_KEY` / `STREAM_API_SECRET` — **не боевые** (отдельное бесплатное приложение
  GetStream или заглушка). Пока GetStream-код не удалён, бэкенд пишет в Stream при создании
  чата, правке чата, оплате тарифа, сохранении профиля — с боевыми ключами staging менял бы
  каналы реальных пользователей. Боевые ключи передаются только команде импорта (A4).
- `APNS_USE_SANDBOX=True` — для сборок из Xcode (sandbox-токены PushKit).
- Платёжные ключи — тестовый режим; `TELEGRAM_ERROR_ALERTS_ENABLED=False` (или отдельный чат).
- Не ставьте на staging cron с `update_chat_status`.

Известные эффекты не-боевых ключей Stream на staging (на проде их нет): `PATCH /api/chats/<id>/`
сохраняет данные, рассылает `chat.updated`, но отвечает `400 STREAM_CHANNEL_UPDATE_FAILED`;
активация бесплатного тарифа и вебхук оплаты падают на синхронизации со Stream после
активации доступа. Тарифы для тестов проще выдавать через админку (`AccessOrder` со статусом
`success` и `expires_at` в будущем).

### A2. Копия данных и обезвреживание

```bash
# на проде (переменные раскрываются внутри контейнера)
docker compose -f docker-compose.prod.yml exec -T database \
  sh -c 'pg_dump -U "$POSTGRES_USER" -Fc "$POSTGRES_DB"' > prod.dump
# на staging: поднять только базу и залить копию
docker compose -f docker-compose.prod.yml up -d database
docker compose -f docker-compose.prod.yml exec -T database \
  sh -c 'pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --no-owner' < prod.dump
```

Сразу после восстановления, **до запуска backend/celery**, выключите доставку реальным
людям — в копии лежат боевые FCM-токены:

```bash
docker compose -f docker-compose.prod.yml run --rm backend python manage.py shell -c "
from push_notifications.models import GCMDevice
from messenger.models import VoipDevice
print('fcm off:', GCMDevice.objects.filter(active=True).update(active=False))
print('voip deleted:', VoipDevice.objects.all().delete())
"
```

Тестировщики входят на staging со своих телефонов — их устройства зарегистрируются заново
(`register-fcm`, `voip-devices`). Не приглашайте с staging реальные номера (`invite-client`
шлёт SMS/WhatsApp).

### A3. Деплой и проверка сервисов

```bash
docker compose -f docker-compose.prod.yml up -d --build
docker compose -f docker-compose.prod.yml ps          # minio-init — Exited (0), остальные Up
docker compose -f docker-compose.prod.yml logs nginx | grep -E "certbot|\[tls\]"
docker compose -f docker-compose.prod.yml logs livekit | grep -E "Starting TURN|starting LiveKit"
```

Ожидаемо: `[tls] сертификат … найден, включаю HTTPS`, у LiveKit `turn.portTLS: 5349,
turn.externalTLS: true`. Проверки снаружи:

```bash
curl -sI https://files.<DOMAIN>/messenger/x | head -1      # 403 (бакет приватный) — MinIO за nginx
curl -s  https://rtc.<DOMAIN>/                              # OK — LiveKit за nginx
openssl s_client -connect <DOMAIN>:443 -servername turn.<DOMAIN> </dev/null 2>/dev/null | grep subject  # сертификат на turn.
```

Затем с авторизованным токеном: `GET /api/messenger/connection-token/` → 200 с `wsUrl`;
отправка сообщения и вложения из тестового приложения; тестовый звонок. После звонка
вебхуки LiveKit должны доходить до бэкенда:

```bash
docker compose -f docker-compose.prod.yml logs livekit | grep "sent webhook" | tail -3   # "statusCode": 200
```

`401` в этих строках — `LIVEKIT_API_KEY`/`SECRET` у livekit и backend различаются; ошибка
соединения — `LIVEKIT_WEBHOOK_URL` недоступен с сервера.

### A4. ОБЯЗАТЕЛЬНО: dry-run по отдельным каналам и сверка со Stream

Пагинация импорта (`created_at_after_or_equal`, от старых к новым) проверена только на
фикстурах, не на настоящем GetStream. Прежде чем запускать полный импорт, на staging
сравните, сколько сообщений импорт **нашёл бы**, с тем, сколько их в Stream на самом деле.

Выберите 5–10 каналов: самый длинный, с тредами (ответы в ветках), с вложениями и
голосовыми, с удалёнными сообщениями, свежий. Для каждого:

```bash
docker compose -f docker-compose.prod.yml exec \
  -e STREAM_API_KEY=<боевой ключ> -e STREAM_API_SECRET=<боевой секрет> \
  backend python manage.py import_getstream --dry-run --channel chat_12_34 -v 2
# [dry-run] GetStream import finished: channels=1 messages_created=1834 messages_skipped=2 attachments=97 errors=0 ...
```

Независимый подсчёт в Stream (другой способ пагинации — `id_lt`, от новых к старым;
треды — через `get_replies`):

```bash
docker compose -f docker-compose.prod.yml exec \
  -e STREAM_API_KEY=<боевой ключ> -e STREAM_API_SECRET=<боевой секрет> \
  backend python manage.py shell -c "
from common.stream_client import chat_client
CID = 'chat_12_34'
ch = chat_client.channel('messaging', CID)

def page_all(fetch):
    out, before = [], None
    while True:
        opts = {'limit': 100}
        if before:
            opts['id_lt'] = before
        msgs = fetch(opts)['messages']
        out += msgs
        if len(msgs) < 100:
            return out
        before = min(msgs, key=lambda m: m['created_at'])['id']   # самое старое на странице

top = page_all(lambda o: ch.query(messages=o))
ids = {m['id'] for m in top if m.get('type') not in ('ephemeral', 'error')}
for parent in [m['id'] for m in top if m.get('reply_count')]:
    ids |= {m['id'] for m in page_all(lambda o: ch.get_replies(parent, **o))
            if m.get('type') not in ('ephemeral', 'error')}
atts = sum(len(m.get('attachments') or []) for m in top)
print(CID, 'stream messages:', len(ids), 'top-level attachments:', atts)
"
```

`messages_created` (+ `messages_linked`, если на staging уже есть сообщения двойной записи)
должен совпасть с `stream messages`; `attachments` — близко к числу вложений
(превью ссылок и giphy не скачиваются: `link_previews`, `unknown_attachments`). Если не
совпало — **не запускать** полный импорт, разобраться (лог `-v 2`, ошибки в stderr).

### A5. Полный импорт на staging и сверка

```bash
docker compose -f docker-compose.prod.yml exec -d \
  -e STREAM_API_KEY=<боевой ключ> -e STREAM_API_SECRET=<боевой секрет> \
  backend sh -c 'python manage.py import_getstream -v 2 > /app/import_staging.log 2>&1'
tail -f app/import_staging.log
```

Импорт идемпотентен и возобновляем: прерванный запуск просто повторите той же командой.
Итоговая строка: `GetStream import finished: channels=… messages_created=… messages_skipped=…
attachments=… errors=N messages_updated=… messages_linked=… unknown_users=… …`. При
`errors > 0` строки ошибок — в логе (`<channel_id>: …`); после исправления перезапустите
для этих каналов (`--channel`).

Сверка по каналам — раздел C4 (на staging так же).

### A6. Тестирование Flutter

Flutter-разработчик собирает приложение на `https://staging.<DOMAIN>` и проходит чек-лист
из [MESSENGER_API.md](MESSENGER_API.md) (раздел 10) и сценарии [CALLS_API.md](CALLS_API.md)
на перенесённой истории: старые чаты, вложения и голосовые из GetStream, ответы, удалённые,
непрочитанные; звонки iOS ↔ Android, в т.ч. из закрытого приложения и в мобильной сети
(TURN/TLS на 443).

---

## B. Прод: деплой и первый полный импорт

### B1. Деплой

DNS, фаервол и `.env.prod` — раздел 0. Затем:

```bash
git pull
docker compose -f docker-compose.prod.yml up -d --build
```

Миграции применяются при старте backend. GetStream-код на месте: **старое приложение
работает как раньше** (сообщения, звонки, пуши Stream). Проверки — как A3.

Что старое приложение заметит уже сейчас: `GET /api/chats/` считает `shouldReply`,
порядок и `lastMessage` по **нашей** базе. Пока не прошёл импорт (и между импортами),
эти поля отстают от Stream. Держите окно между B2 и C коротким; при необходимости
повторяйте дельта-импорт (C2) по расписанию.

### B2. Полный импорт

```bash
date -u +%Y-%m-%dT%H:%M:%SZ        # запомнить: T_FULL — время старта
docker compose -f docker-compose.prod.yml exec -d backend \
  sh -c 'python manage.py import_getstream -v 2 > /app/import_full.log 2>&1'
tail -f app/import_full.log
```

Долго (часы — каналы по одному, файлы потоком). Импорт не шлёт событий и пушей.
Цель: `errors=0`; каналы с ошибками — перезапуск `--channel <id>`.

---

## C. Окно переключения

### C1. Релиз приложения и принудительное обновление

Новое приложение в сторах; включить принудительное обновление (минимальная версия) —
механизм на стороне приложения/стора. С этого момента старое приложение не пишет в Stream.
Это **точка невозврата**.

### C2. Дельта-импорт

Всё, что написали в старом приложении после старта полного импорта:

```bash
docker compose -f docker-compose.prod.yml exec backend \
  python manage.py import_getstream --since <T_FULL минус 1 час> -v 2
```

`--since` — ISO 8601 (`2026-11-20T09:00:00Z` или дата `2026-11-20`; без зоны = UTC).
Запас в час — потому что полный импорт идёт каналами по очереди.

### C3. ФИНАЛЬНЫЙ полный прогон — без `--since`

```bash
docker compose -f docker-compose.prod.yml exec backend \
  sh -c 'python manage.py import_getstream -v 2 > /app/import_final.log 2>&1'
```

Обязателен: дельта `--since` **не видит** правки и удаления старых сообщений и ответы в
тредах к сообщениям старше `--since`. Полный прогон идемпотентен: уже перенесённое не
дублируется и не перекачивается, обновляются только удаления/правки
(`messages_updated`) и докачиваются пропущенные файлы. Ожидаемо `messages_created`
небольшое, `errors=0`.

Пока GetStream не отключён, этот прогон можно и нужно повторять ещё несколько дней:
приложения, давно не открывавшиеся, могли успеть что-то отправить до проверки версии.

### C4. Сверка количества по каналам

Сумма из финального прогона — первый сигнал. Затем — по каналам: независимый подсчёт в
Stream (скрипт из A4) против нашей базы:

```bash
docker compose -f docker-compose.prod.yml exec backend python manage.py shell -c "
from messenger.models import Message
CID = 'chat_12_34'
qs = Message.objects.filter(chat__channel_id=CID, stream_id__isnull=False)
print(CID, 'imported:', qs.count(), 'deleted:', qs.filter(deleted_at__isnull=False).count())
"
```

Для точного расхождения — сравнить множества id (`ids` из скрипта A4 против
`set(qs.values_list('stream_id', flat=True))`). Проверить: все каналы, на которых были
ошибки; 20 самых длинных; 20 случайных. Каналы без сообщений у нас:

```bash
docker compose -f docker-compose.prod.yml exec backend python manage.py shell -c "
from chat_access.models import Chat
empty = Chat.objects.filter(last_message__isnull=True).values_list('channel_id', flat=True)
print(len(empty), list(empty)[:50])
"
```

(должны быть пустыми и в Stream). Расхождения — перезапуск `--channel <id>` и повторная
сверка.

---

## D. После переключения

### D1. GetStream больше не источник

Импорт больше не запускается, данные в Stream не меняются. **Аккаунт и ключи GetStream пока
не отключать**: до уборки кода бэкенд всё ещё обращается к Stream — при создании чата, правке
чата (`PATCH /api/chats/<id>/` отвечает ошибкой `STREAM_CHANNEL_UPDATE_FAILED`, если Stream
недоступен), оплате и активации тарифа (вебхук оплаты прерывается на синхронизации со Stream),
сохранении профиля, системных сообщениях старого эндпоинта.

### D2. Уборка (отдельный релиз, спека §9)

Удалить: `common/stream_client.py`, `account/services/stream.py`, синк пользователя в
`User.save`, `GetStreamTokenView` и `streamToken` в ответах логина (и Telegram-логина),
сигнал удаления канала, команду `update_chat_status`, `ChatConsumer`/`routing.py`/слой
Django Channels (`ws/chats/`), `POST /api/stream/send-system-message/`, настройки `STREAM_*`,
коды ошибок `STREAM_*`, пакет `stream-chat`. Команду `import_getstream` — после того как
GetStream отключён.

### D3. Отключение GetStream

Только после деплоя D2: удалить ключи из `.env.prod` и отключить аккаунт GetStream.
