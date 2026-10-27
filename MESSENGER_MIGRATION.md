# Переход с GetStream на свой мессенджер — runbook

Порядок действий для бэкенда/DevOps. API для приложения — [MESSENGER_API.md](MESSENGER_API.md)
и [CALLS_API.md](CALLS_API.md). Дизайн — `docs/superpowers/specs/2026-10-25-own-messenger-design.md`.

Короткая схема:

```
A. Staging (на прод-сервере, отдельный проект): копия прода → обязательный dry-run по каналам →
           полный импорт → тесты Flutter → после C — удаление staging
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

Для staging на этом же сервере — ещё четыре записи и отдельный сертификат (A1).

### 0.2. Порты и фаервол

| Порт | Открыт наружу | Кто |
|---|---|---|
| 80/tcp, 443/tcp | да | nginx (443: https и TURN/TLS по SNI; 80 при наличии сертификата — только проверка certbot и 301 на https) |
| 7881/tcp | да | LiveKit, WebRTC по TCP |
| 7882/udp | да | LiveKit, медиа (один UDP-порт) |
| 3478/udp | да | LiveKit TURN/UDP |
| 7880/tcp, 5349/tcp | **нет** — только из docker-сетей | LiveKit API/сигналинг и TURN-слушатель; снаружи доступны через nginx (`rtc.`, `turn.`) |
| 9000, 9001, 6379 | нет (слушают 127.0.0.1) | MinIO, Redis |
| 17881/tcp, 17882/udp, 13478/udp (17880, 15349, 16379 — нет) | только пока работает staging | staging-LiveKit (A1) |

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
| `MESSENGER_LEGACY_MODE` | `True` до переключения (B), `False` — с шага C1. На staging — `False` |

**`MESSENGER_LEGACY_MODE`** (по умолчанию `True`) — переходный режим, пока клиенты пользуются
старым приложением, которое пишет только в GetStream:

| | `True` (прод до C1) | `False` (staging; прод с C1) |
|---|---|---|
| `shouldReply` в `GET /api/chats/`, `GET /api/chats/<id>/`, ответе приглашения | по последнему сообщению в GetStream (как раньше; Stream недоступен → `false`) | по последнему сообщению в нашей БД |
| Порядок `GET /api/chats/` | по дате создания чата (как раньше) | по `lastMessageAt` |
| Приветствие нового чата | сохраняется и публикуется, но **без** нашего FCM-пуша (старое приложение получает пуш от Stream и пуш-приглашение) | с пушем, как обычное сообщение |

> ⚠️ **`S3_KMS_SECRET_KEY` терять и менять нельзя**: все файлы в MinIO зашифрованы им
> (SSE-S3). Сохраните его в хранилище секретов вместе с бэкапом тома `minio-data`.

Пустые значения в `.env` пишите без комментария в той же строке: docker compose прочитает
`KEY=   # текст` как значение `# текст`.

### 0.4. Место на диске

Импорт скачивает все вложения из GetStream в MinIO (том `minio-data`). Оцените объём по
статистике хранилища в панели GetStream и оставьте запас ×1.5.

### 0.5. Внешние вызовы — только https

С сертификатом nginx отвечает на `http://<DOMAIN>/…` редиректом **301** на https (кроме
проверки certbot). POST после 301 большинство клиентов повторяет как GET или не повторяет
вовсе — запрос теряется. До деплоя проверьте, что все, кто вызывает бэкенд снаружи,
настроены на `https://<DOMAIN>`:

- платёжный провайдер — URL колбэка `https://<DOMAIN>/api/payment/webhook/…`
  (в личном кабинете провайдера);
- MedCRM — базовый URL интеграции `https://<DOMAIN>/api/integration/medcrm/…`;
- Telegram-боты — `getWebhookInfo` каждого бота: `url` начинается с `https://`;
- прочие партнёры (MamaDoc и т. п.), если они ходят к нам.

После деплоя — проверить в логах nginx, что на `:80` не приходят POST с ответом 301:

```bash
docker compose -f docker-compose.prod.yml logs nginx | grep '"POST .* 301 ' | tail
```

### 0.6. Образ MinIO собирается из исходников

MinIO больше не публикует образы `minio/minio` и `minio/mc` (Docker Hub отвечает
`pull access denied`). Сервисы `minio` и `minio-init` используют один локальный образ
`profichat/minio:<релиз>`, который compose собирает из `minio/Dockerfile`: исходники
MinIO и mc клонируются с GitHub по тегу `RELEASE.*` и собираются Go из официального
образа `golang`. Бинарник `minio` внутри — тот же релиз (`minio --version`), процесс
работает не от root (uid 10001).

- **Первая сборка** — около 2–4 минут на ноутбуке разработчика (замер с `--no-cache`),
  на небольшом VPS дольше: скачиваются Go-модули (нужен доступ к GitHub и proxy.golang.org)
  и компилируется MinIO, что требовательно к памяти — на сервере с 1–2 ГБ RAM добавьте swap.
  Сборку делает обычный `up -d --build`; можно заранее:
  `docker compose -f docker-compose.prod.yml build minio`. Дальше образ берётся из кэша.
- **Обновление релиза:** в `minio/Dockerfile` поменять `MINIO_RELEASE` (и при
  необходимости `MC_RELEASE`; теги — github.com/minio/minio/tags, github.com/minio/mc/tags),
  сверить `GO_IMAGE` с директивами `go`/`toolchain` в `go.mod` релиза, затем поменять тег
  `image: profichat/minio:<релиз>` у `minio` и `minio-init` в `docker-compose.yml` и
  `docker-compose.prod.yml` и `profichat-staging/minio:<релиз>` в `docker-compose.staging.yml`
  (новый тег — сигнал compose пересобрать) и выполнить `up -d --build minio minio-init`.
- Staging собирает тот же Dockerfile под **своим** тегом `profichat-staging/minio:<релиз>`:
  `up -d --build` staging не перезаписывает образ, на котором работает прод.
- Том `minio-data`, созданный **старым** образом `minio/minio` (работал от root), новому
  непривилегированному процессу недоступен на запись. Если такой том уже есть:
  `docker compose -f docker-compose.prod.yml run --rm --no-deps --user root --entrypoint chown minio -R 10001:10001 /data`.

### 0.7. Версия Redis

Прод-Redis этот переход **не трогает**: в `docker-compose.prod.yml` по-прежнему `image: redis`
без тега, как и раньше — `up -d` использует уже скачанный на сервере образ. Закреплён
только staging (`redis:8.2` в `docker-compose.staging.yml`): у него свои пустые данные.

Закрепить тег прода можно позже, отдельным изменением: посмотреть работающую версию
`docker compose -f docker-compose.prod.yml exec redis redis-server --version`
(`v=7.2.4` → тег `redis:7.2.4`) и указать **ровно её**. Тег новее — одностороннее обновление
формата данных, тег старее — Redis не прочитает свой `dump.rdb` (RDB более новой версии он
не читает).

---

## A. Staging на прод-сервере (обязательно до прода)

Цель — прогнать импорт на копии боевых данных и дать Flutter-разработчику тестировать новое
приложение, **не отправляя ничего реальным людям** и не трогая боевой GetStream.

Staging работает **на том же сервере, что и прод**, отдельным compose-проектом
`profichat-staging` (`docker-compose.staging.yml`, свой каталог checkout-а, свои тома, база,
Redis, MinIO, Centrifugo, LiveKit). Своего nginx у staging нет: 80/443 держит прод-nginx и,
когда в `.env.prod` задан `STAGING_DOMAIN`, проксирует staging-имена в staging-контейнеры
через общую сеть `profichat-edge`:

```
Интернет ─80/443─ прод-nginx ─┬─ сеть прода:      backend, centrifugo, minio      ← <DOMAIN>, files./rtc./turn.<DOMAIN>
                              └─ profichat-edge:   staging-backend, staging-centrifugo,
                                                   staging-minio, staging-static   ← staging.<DOMAIN>, files./rtc./turn.staging.<DOMAIN>
LiveKit (сеть хоста): прод 7880 / 7881 / 7882 / 3478 / 5349, staging 17880 / 17881 / 17882 / 13478 / 15349
Redis для LiveKit:    прод 127.0.0.1:6379,                   staging 127.0.0.1:16379
```

Прод от staging не зависит: staging-маршруты nginx резолвят имена при запросе, без staging
они отвечают 502, а прод-nginx стартует и работает как обычно. В `profichat-edge` из прода
входит только nginx — прод-backend, база и Redis staging-контейнерам не видны.

> ### ⚠️ Безопасность: прод и staging на одном Docker
>
> - **Каждая** staging-команда — с `-f docker-compose.staging.yml` и **только из каталога
>   staging** (A3). В этом файле `name: profichat-staging`: контейнеры, тома и сеть называются
>   `profichat-staging_*`, что бы ни было в имени каталога, поэтому
>   `docker compose -f docker-compose.staging.yml down -v` удаляет **только** тома staging.
> - **Никогда** `down -v` (и `rm -v`, `volume rm`) без `-f docker-compose.staging.yml`. Без `-f`
>   compose берёт `docker-compose.yml` и проект = **имя каталога**; если оно совпадёт с
>   каталогом прода (например, оба `profichat-back`), `down -v` удалит тома **прода**
>   (`database-storage`, `redis-data`, … — имена те же). Страховка — `.env` с `COMPOSE_FILE` в
>   каталоге staging (A3) и каталог staging с другим именем.
> - Не передавайте `-p`: он перекрывает `name:`.
> - Перед разрушительной командой: `docker compose -f docker-compose.staging.yml config | head -1`
>   → `name: profichat-staging`; `docker compose ls` — у прода и staging разные `NAME` и
>   `CONFIG FILES`.
> - **Никаких** `docker system prune --volumes` / `docker volume prune` на этом сервере.
> - В staging-базе — копия боевых персональных и медицинских данных: дамп удалить сразу после
>   восстановления (A4), доступ к staging — как к проду.

### A1. DNS, фаервол, сертификат staging (ДО включения `STAGING_DOMAIN`)

**DNS** — четыре A-записи на IP этого же сервера: `staging.<DOMAIN>`,
`files.staging.<DOMAIN>`, `rtc.staging.<DOMAIN>`, `turn.staging.<DOMAIN>`. Дождитесь, пока
все четыре резолвятся (`dig +short files.staging.<DOMAIN>` и т. д.), и только потом
переходите к A2: сертификат staging запрашивается при старте прод-nginx.

**Сертификат** — отдельный (`--cert-name staging.<DOMAIN>`, четыре имени). Прод-nginx
запрашивает его при старте **после** сертификата прода; ошибка только пишется в лог
(`[certbot] не удалось получить сертификат staging … — прод не затронут`) и не мешает ни
выпуску, ни продлению прода. Пока сертификата нет, staging работает только по http :80
(`[staging] … staging только по http :80`). Повторная попытка — только перезапуском
прод-nginx (`docker compose -f docker-compose.prod.yml restart nginx` в каталоге прода): это
несколько секунд простоя прода на 80/443, поэтому — в часы наименьшей активности и не
чаще нескольких раз в час (лимит Let's Encrypt на неудачные проверки). Фоновый
`certbot renew` продлевает оба сертификата, хук перечитывает nginx без перезапуска.

**Фаервол** — порты staging-LiveKit (сеть хоста):

| Порт | Наружу | Что |
|---|---|---|
| 17881/tcp | да | WebRTC по TCP |
| 17882/udp | да | медиа (один UDP-порт) |
| 13478/udp | да | TURN/UDP |
| 17880/tcp, 15349/tcp | **нет** — только из docker-сетей | API/сигналинг и TURN-слушатель; снаружи через прод-nginx (`rtc.`/`turn.staging.`) |
| 16379/tcp | нет (слушает 127.0.0.1) | staging-Redis для LiveKit |

```bash
ufw allow 17881/tcp
ufw allow 17882/udp
ufw allow 13478/udp
ufw allow from 172.16.0.0/12 to any port 17880,15349 proto tcp   # docker-сети → staging-LiveKit
```

Docker может выдавать сетям и `192.168.0.0/16` — проверьте подсети и при необходимости
добавьте такое же правило: `docker network inspect profichat-edge profichat-staging_default
-f '{{.Name}} {{(index .IPAM.Config 0).Subnet}}'` (первая сеть появится после A2, вторая — после A5).

### A2. Прод-nginx с поддержкой staging (один раз)

Нужен прод-nginx из этой версии (`STAGING_DOMAIN`, сеть `profichat-edge`). Сеть создаёт сам
`docker-compose.prod.yml` при запуске nginx — прод-деплой от ручных шагов не зависит.

> **Не создавайте сеть вручную** (`docker network create profichat-edge`): compose прода
> откажется её использовать — `network profichat-edge was found but has incorrect label
> com.docker.compose.network`. Если так случилось: `docker network rm profichat-edge`
> (в ней не должно быть контейнеров) и повторить `up`.

`STAGING_DOMAIN` записывается в `.env.prod` заменой строки или дописыванием с новой строки
(простой `echo >> .env.prod` приклеил бы значение к последней переменной, если в конце файла
нет перевода строки, и испортил бы её). Значение — **только** `staging.<DOMAIN>` (или другой
домен, не пересекающийся с прод-именами): если оно совпадает с `<DOMAIN>`,
`www./files./rtc./turn.<DOMAIN>` или `<DOMAIN>` лежит внутри него, nginx его отвергает
(`[staging] !!! STAGING_DOMAIN=… ОТВЕРГНУТ`) и работает без staging.

```bash
# в каталоге прода; одна и та же функция — для включения (A2) и выключения (A9)
set_staging_domain() {
  if grep -q '^STAGING_DOMAIN=' .env.prod; then
    sed -i "s|^STAGING_DOMAIN=.*|STAGING_DOMAIN=$1|" .env.prod
  else
    printf '\nSTAGING_DOMAIN=%s\n' "$1" >> .env.prod
  fi
  grep -c '^STAGING_DOMAIN=' .env.prod; grep '^STAGING_DOMAIN=' .env.prod   # ровно одна строка
}
```

**Прод ещё на старой версии (до B)** — обновить только nginx, не трогая остальные сервисы:

```bash
cd <каталог прода>
cp .env.prod .env.prod.bak-staging                              # для отката
git fetch origin
git checkout origin/<ветка> -- nginx docker-compose.prod.yml   # только эти пути
set_staging_domain staging.<DOMAIN>                             # GET_CERTS=True — уже стоит
docker compose -f docker-compose.prod.yml build nginx
docker compose -f docker-compose.prod.yml up -d --no-deps nginx
docker compose -f docker-compose.prod.yml logs nginx | grep -E "certbot|\[tls\]|\[staging\]"
curl -sI https://<DOMAIN>/admin/login/ | head -1                # прод отвечает как раньше
```

- `--no-deps` обязателен: без него compose поднял бы новые сервисы прода (centrifugo, minio,
  livekit). Делать в часы наименьшей активности: nginx пересоздаётся и при старте ходит в
  Let's Encrypt.
- Это тот же nginx, что выкатывает B1: 443 переходит на SNI-маршрутизацию, сертификат прода
  перевыпускается с `files./rtc./turn.<DOMAIN>` (п. 0.1). Нет DNS поддоменов прода — в логе
  `[certbot] не удалось…`, старый сертификат на `<DOMAIN>` работает дальше.
- **Пока идёт A (до B1) каталог прода смешанный**: `nginx/` и `docker-compose.prod.yml` — из
  новой версии, код и остальное — из старой. Любой деплой прода в это время (хотфикс) —
  **только с именем сервиса и `--no-deps`**:
  `git pull` (если конфликтует с этими путями — сначала откат файлов, см. ниже) и
  `docker compose -f docker-compose.prod.yml up -d --build --no-deps backend celery celery-beat`.
  Никогда `up -d` / `up -d --build` без списка сервисов — это частичный деплой B.
- Перед B1 вернуть файлы к текущей версии checkout-а (на работающий nginx это не влияет):
  `git checkout HEAD -- nginx docker-compose.prod.yml`, затем `git pull` как в B1.

**Откат A2** (staging не нужен или новый nginx ведёт себя не так), в каталоге прода:

```bash
# 1. staging, если запущен — остановить (A9, шаг 1), иначе сеть profichat-edge не удалится
# 2. выключить staging и удалить его сертификат, пока работает новый nginx
set_staging_domain ''
docker compose -f docker-compose.prod.yml up -d --no-deps --force-recreate nginx
docker compose -f docker-compose.prod.yml exec nginx certbot delete --cert-name staging.<DOMAIN> --non-interactive
# 3. вернуть старые nginx/ и compose, собрать и пересоздать старый nginx
git checkout HEAD -- nginx docker-compose.prod.yml
docker compose -f docker-compose.prod.yml build nginx
docker compose -f docker-compose.prod.yml up -d --no-deps --force-recreate nginx
docker network rm profichat-edge                     # старый compose её не знает; пустую — удалить
# 4. сертификат прода: новый nginx мог перевыпустить его через webroot (authenticator = webroot,
#    плюс имена files./rtc./turn.). Старый nginx не отдаёт /.well-known/acme-challenge/ из
#    webroot — продление такого сертификата будет падать. Перевыпустить через плагин nginx:
docker compose -f docker-compose.prod.yml exec nginx \
  certbot certonly --nginx --cert-name <DOMAIN> -d <DOMAIN> --non-interactive --force-renewal
docker compose -f docker-compose.prod.yml exec nginx nginx -s reload
docker compose -f docker-compose.prod.yml exec nginx certbot renew --dry-run   # должно пройти
curl -sI https://<DOMAIN>/admin/login/ | head -1
```

Путь `live/<DOMAIN>` при этом не меняется, старый конфиг nginx продолжает его находить.
`.env.prod.bak-staging` — копия до A2; после отката её можно удалить.

**Прод уже на этой версии** — только `STAGING_DOMAIN` и пересоздать nginx (в часы
наименьшей активности):

```bash
set_staging_domain staging.<DOMAIN>
docker compose -f docker-compose.prod.yml up -d --no-deps --force-recreate nginx
```

### A3. Каталог staging, `.env.staging`, лимиты

Staging — **отдельный checkout** со своей веткой: `./app` монтируется в контейнеры, а в
каталоге прода лежит код прода. Имя каталога — не такое, как у прода:

```bash
git clone <repo> /srv/profichat-staging-src
cd /srv/profichat-staging-src
git checkout <ветка>
cp .env.staging.example .env.staging          # заполнить, см. ниже
echo 'COMPOSE_FILE=docker-compose.staging.yml' > .env   # страховка: голый `docker compose` → staging
```

`.env.staging` — по образцу `.env.staging.example` (не копия `.env.prod`!). Отличия от прода:

| Переменная | Значение на staging |
|---|---|
| `DOMAIN`, `DJANGO_ALLOWED_HOSTS` | `staging.<DOMAIN>` (= `STAGING_DOMAIN` прода) |
| `CENTRIFUGO_API_URL` | `http://staging-centrifugo:8000/api` |
| `CENTRIFUGO_WS_URL` | `wss://staging.<DOMAIN>/connection/websocket` |
| `S3_ENDPOINT_URL` | `http://staging-minio:9000` |
| `S3_PUBLIC_ENDPOINT_URL` | `https://files.staging.<DOMAIN>` |
| `LIVEKIT_URL` | `wss://rtc.staging.<DOMAIN>` |
| `LIVEKIT_API_URL` | `http://host.docker.internal:17880` |
| `LIVEKIT_TURN_DOMAIN` | `turn.staging.<DOMAIN>` |
| `LIVEKIT_WEBHOOK_URL` | `https://staging.<DOMAIN>/api/messenger/livekit-webhook/` |
| `LIVEKIT_API_KEY`, `LIVEKIT_API_SECRET` | **свои**, не прод |
| `SECRET_KEY`, `POSTGRES_PASSWORD`, `CENTRIFUGO_*` ключи, `S3_ACCESS_KEY`/`S3_SECRET_KEY`, `S3_KMS_SECRET_KEY` | свои (генерировать как в 0.3) |
| `MESSENGER_LEGACY_MODE` | `False` — staging проверяет новое приложение (0.3) |
| `APNS_USE_SANDBOX` | `True` — для сборок из Xcode (sandbox-токены PushKit) |

Обязательно не боевые:

- `STREAM_API_KEY` / `STREAM_API_SECRET` — **не боевые** (отдельное бесплатное приложение
  GetStream или заглушка). Пока GetStream-код не удалён, бэкенд пишет в Stream при создании
  чата, правке чата, оплате тарифа, сохранении профиля — с боевыми ключами staging менял бы
  каналы реальных пользователей. Боевые ключи передаются только команде импорта (A6, A7).
- Все внешние интеграции — **не боевые**:
  - `RAVEN_API_KEY` (SMS/WhatsApp: OTP, приглашения) — тестовый ключ или заглушка, иначе
    staging шлёт SMS/WhatsApp реальным номерам из копии базы;
  - `MEDCRM_API_KEY`, `MEDCRM_SSO_INTEGRATION_SECRET`, `MEDCRM_SSO_WEB_URL` — тестовые/пустые;
  - `MAMADOC_API_URL`, `MAMADOC_API_KEY` — тестовый стенд или пусто;
  - `PAYMENT_API_TOKEN` — тестовый режим провайдера (колбэки провайдера — на staging-домен);
  - `TELEGRAM_BOT_TOKEN`, `TELEGRAM_AUTH_BOT_TOKEN` — отдельные тестовые боты (у одного
    токена Telegram один webhook: боевой токен на staging перехватит webhook прода),
    `TELEGRAM_*_WEBHOOK_SECRET` — свои, `TELEGRAM_ERROR_ALERTS_ENABLED=False` (или отдельный чат);
  - `SENTRY_DSN` — пусто или отдельный проект.
- Не ставьте на staging cron с `update_chat_status`.

Известные эффекты не-боевых ключей Stream на staging (на проде их нет): `PATCH /api/chats/<id>/`
сохраняет данные, рассылает `chat.updated`, но отвечает `400 STREAM_CHANNEL_UPDATE_FAILED`;
активация бесплатного тарифа и вебхук оплаты падают на синхронизации со Stream после
активации доступа. Тарифы для тестов проще выдавать через админку (`AccessOrder` со статусом
`success` и `expires_at` в будущем).

**Лимиты ресурсов.** У каждого staging-сервиса в `docker-compose.staging.yml` есть
`deploy.resources.limits` — потолок CPU/памяти, чтобы staging (и импорт) не отнял ресурсы у
прода:

| Сервис | CPU | Память |
|---|---|---|
| `staging-backend` (в нём же идёт импорт) | 1 | 1 ГБ |
| `database` | 1 | 1 ГБ |
| `livekit` | 1 | 512 МБ |
| `celery` (`--concurrency 2`) | 0.5 | 768 МБ |
| `redis`, `staging-minio` | 0.5 | 512 МБ |
| `staging-centrifugo` | 0.5 | 256 МБ |
| `celery-beat` | 0.25 | 256 МБ |
| `minio-init`, `staging-static` | 0.25 | 128 / 64 МБ |

Кроме лимитов, у всех staging-сервисов (`x-staging-common` в файле): `oom_score_adj: 800` —
при нехватке памяти на хосте ядро убивает процессы staging раньше прода; `cpu_shares: 256` —
при борьбе за CPU прод (1024 по умолчанию) получает вчетверо больший вес; логи `json-file`
не больше 3 × 10 МБ на контейнер.

Сумма — около 5 CPU и 5 ГБ; это потолки, а не резерв: в простое staging берёт много меньше.
Подбор: посмотреть ядра и свободную память прода (`nproc`, `free -h`,
`docker stats --no-stream`) и держать сумму лимитов staging не больше того, что прод не
использует в пике; на маленьком сервере уменьшить в первую очередь `staging-backend`,
`database`, `livekit`. Изменить значения в файле и применить:
`docker compose -f docker-compose.staging.yml up -d` (пересоздаст изменённые сервисы).
Упёршийся в лимит памяти контейнер перезапускается (OOM) — видно в `docker compose … ps`
и `docker inspect … --format '{{.State.OOMKilled}}'`. Диск и сеть лимитами не ограничены —
см. A7.

### A4. Копия данных и обезвреживание

```bash
# в каталоге ПРОДА (нагрузка на прод-базу — в часы наименьшей активности)
docker compose -f docker-compose.prod.yml exec -T database \
  sh -c 'pg_dump -U "$POSTGRES_USER" -Fc "$POSTGRES_DB"' > /root/prod.dump

# в каталоге STAGING: поднять только базу и залить копию
docker compose -f docker-compose.staging.yml up -d database
docker compose -f docker-compose.staging.yml exec -T database \
  sh -c 'pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --no-owner' < /root/prod.dump
rm /root/prod.dump          # персональные данные: дамп не хранить
```

Сразу после восстановления, **до запуска staging-backend/celery**, выключите доставку
реальным людям — в копии лежат боевые FCM-токены. Сначала миграции (в дампе прода ещё нет
таблиц мессенджера), затем отключение:

```bash
docker compose -f docker-compose.staging.yml run --rm staging-backend sh -c '
python manage.py migrate &&
python manage.py shell -c "
from push_notifications.models import GCMDevice
from messenger.models import VoipDevice
print(\"fcm off:\", GCMDevice.objects.filter(active=True).update(active=False))
print(\"voip deleted:\", VoipDevice.objects.all().delete())
"'
```

Тестировщики входят на staging со своих телефонов — их устройства зарегистрируются заново
(`register-fcm`, `voip-devices`). Не приглашайте с staging реальные номера (`invite-client`
шлёт SMS/WhatsApp).

Медиа прода (аватары и т. п.) в копию не попадают; при необходимости скопировать том
(имя тома прода — `docker volume ls | grep media_volume`):
`docker run --rm -v <прод-проект>_media_volume:/from:ro -v profichat-staging_media_volume:/to alpine cp -a /from/. /to/`.

### A5. Деплой и проверка сервисов

```bash
# в каталоге STAGING
docker compose -f docker-compose.staging.yml up -d --build
docker compose -f docker-compose.staging.yml ps          # minio-init — Exited (0), остальные Up
docker compose ls                                        # profichat-staging и прод — разные проекты
docker compose -f docker-compose.staging.yml logs livekit | grep -E "Starting TURN|starting LiveKit"
# в каталоге ПРОДА
docker compose -f docker-compose.prod.yml logs nginx | grep -E "certbot|\[tls\]|\[staging\]"
```

Ожидаемо: `[staging] staging.<DOMAIN>: HTTPS включён`; у staging-LiveKit `portHttp: 17880`,
`rtc.portTCP: 17881`, `rtc.portUDP: 17882`, `turn.portTLS: 15349`, `turn.portUDP: 13478`,
`turn.relay_range_start: 41000`, redis `127.0.0.1:16379`. Проверки снаружи:

```bash
curl -sI https://staging.<DOMAIN>/admin/login/ | head -1           # 200 — staging-backend
curl -sI https://files.staging.<DOMAIN>/messenger/x | head -1      # 403 (бакет приватный) — staging-MinIO
curl -s  https://rtc.staging.<DOMAIN>/                              # OK — staging-LiveKit
openssl s_client -connect staging.<DOMAIN>:443 -servername turn.staging.<DOMAIN> </dev/null 2>/dev/null | grep subject  # CN=staging.<DOMAIN>
curl -sI https://<DOMAIN>/admin/login/ | head -1                   # прод — как раньше
docker stats --no-stream $(docker compose -f docker-compose.staging.yml ps -q)   # потребление и лимиты
```

Затем с авторизованным токеном staging: `GET /api/messenger/connection-token/` → 200 с
`wsUrl` на `staging.<DOMAIN>`; отправка сообщения и вложения из тестового приложения;
тестовый звонок. После звонка вебхуки staging-LiveKit должны доходить до staging-backend:

```bash
docker compose -f docker-compose.staging.yml logs livekit | grep "sent webhook" | tail -3   # "statusCode": 200
```

`401` в этих строках — `LIVEKIT_API_KEY`/`SECRET` у livekit и staging-backend различаются;
ошибка соединения — `LIVEKIT_WEBHOOK_URL` недоступен с сервера.

### A6. ОБЯЗАТЕЛЬНО: dry-run по отдельным каналам и сверка со Stream

Пагинация импорта (`created_at_after_or_equal`, от старых к новым) проверена только на
фикстурах, не на настоящем GetStream. Прежде чем запускать полный импорт, на staging
сравните, сколько сообщений импорт **нашёл бы**, с тем, сколько их в Stream на самом деле.

Выберите 5–10 каналов: самый длинный, с тредами (ответы в ветках), с вложениями и
голосовыми, с удалёнными сообщениями, свежий. Для каждого:

```bash
docker compose -f docker-compose.staging.yml exec \
  -e STREAM_API_KEY=<боевой ключ> -e STREAM_API_SECRET=<боевой секрет> \
  staging-backend python manage.py import_getstream --dry-run --channel chat_12_34 -v 2
# [dry-run] GetStream import finished: channels=1 messages_created=1834 messages_skipped=2 attachments=97 errors=0 ...
```

Независимый подсчёт в Stream (другой способ пагинации — `id_lt`, от новых к старым;
треды — через `get_replies`):

```bash
docker compose -f docker-compose.staging.yml exec \
  -e STREAM_API_KEY=<боевой ключ> -e STREAM_API_SECRET=<боевой секрет> \
  staging-backend python manage.py shell -c "
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

### A7. Полный импорт на staging и сверка

```bash
docker compose -f docker-compose.staging.yml exec -d \
  -e STREAM_API_KEY=<боевой ключ> -e STREAM_API_SECRET=<боевой секрет> \
  staging-backend sh -c 'python manage.py import_getstream -v 2 > /app/import_staging.log 2>&1'
tail -f app/import_staging.log
```

**Нагрузка на прод.** Импорт идёт внутри `staging-backend` и ограничен его лимитом (1 CPU,
1 ГБ — A3), база и MinIO staging — своими. Не ограничены диск и сеть: импорт скачивает все
вложения из GetStream (входящий канал сервера) и пишет их в том `profichat-staging_minio-data`.
Поэтому:

- запускайте в часы наименьшей активности прода (ночь) и смотрите `docker stats` и время
  ответа прода (`curl -o /dev/null -s -w '%{time_total}\n' https://<DOMAIN>/admin/login/`);
- место на диске — как в 0.4, но **ещё раз** для staging (прод и staging хранят вложения
  отдельно). Перед стартом и каждые полчаса во время импорта:

  ```bash
  df -h /var/lib/docker                                         # колонки Avail и Use%
  docker system df -v | grep profichat-staging_minio-data       # сколько уже занял staging
  ```

  **Правило остановки:** свободно меньше **20 %** диска или меньше **20 ГБ** (что наступит
  раньше) — немедленно остановить импорт (команда ниже) и освободить место; прод при полном
  диске падает (база, Redis, MinIO не могут писать). Освободить: `down -v` staging (A9, шаг 1)
  или расширить диск; продолжать только при запасе выше порога на весь оставшийся объём;
- остановить в любой момент безопасно (импорт возобновляем):
  `docker compose -f docker-compose.staging.yml restart staging-backend` — процесс импорта
  завершится вместе с контейнером; продолжить — той же командой `exec -d`.

Импорт идемпотентен и возобновляем: прерванный запуск просто повторите той же командой.
Итоговая строка: `GetStream import finished: channels=… messages_created=… messages_skipped=…
attachments=… errors=N messages_updated=… messages_linked=… unknown_users=… …`. При
`errors > 0` строки ошибок — в логе (`<channel_id>: …`); после исправления перезапустите
для этих каналов (`--channel`).

Не скачавшееся вложение не теряется: исходное вложение Stream с ключом
`import_failed_index` (номер вложения в сообщении) остаётся в `extra_data["stream_attachments"]`
сообщения и убирается, когда повторный запуск файл скачал. Найти такие сообщения:

```bash
docker compose -f docker-compose.staging.yml exec staging-backend python manage.py shell -c "
from messenger.models import Message
qs = Message.objects.filter(extra_data__has_key='stream_attachments')
bad = [m.pk for m in qs if any('import_failed_index' in a for a in m.extra_data['stream_attachments'])]
print(len(bad), bad[:50])
"
```

Связывание с сообщениями «двойной записи» (`messages_linked`) — только для системных
сообщений и приветствия (первого обычного сообщения специалиста), в пределах ±60 с и с
текстом без учёта пробелов по краям. Одинаковые обычные сообщения (например, «Да» в старом и
в новом приложении) остаются двумя сообщениями.

Сверка по каналам — раздел C4 (на staging так же, с `-f docker-compose.staging.yml exec staging-backend`).

### A8. Тестирование Flutter

Flutter-разработчик собирает приложение на `https://staging.<DOMAIN>` и проходит чек-лист
из [MESSENGER_API.md](MESSENGER_API.md) (раздел 10) и сценарии [CALLS_API.md](CALLS_API.md)
на перенесённой истории: старые чаты, вложения и голосовые из GetStream, ответы, удалённые,
непрочитанные; звонки iOS ↔ Android, в т.ч. из закрытого приложения и в мобильной сети
(TURN/TLS на 443).

### A9. Удаление staging (после переключения)

Когда staging больше не нужен (после C4, Flutter-тесты закончены):

```bash
# 1. в каталоге STAGING — только проект profichat-staging (name: в файле)
cd /srv/profichat-staging-src
docker compose -f docker-compose.staging.yml config | head -1     # name: profichat-staging
docker compose -f docker-compose.staging.yml down -v
docker volume ls | grep profichat-staging_                          # пусто
docker compose ls                                                   # остался только прод

# 2. в каталоге ПРОДА — выключить staging в nginx и удалить его сертификат (до удаления DNS,
#    иначе фоновый certbot renew будет пытаться продлить staging и писать ошибки)
cd <каталог прода>
# функция из A2 — в новой SSH-сессии её нет, поэтому определяем заново (замена строки, без echo >>)
set_staging_domain() {
  if grep -q '^STAGING_DOMAIN=' .env.prod; then
    sed -i "s|^STAGING_DOMAIN=.*|STAGING_DOMAIN=$1|" .env.prod
  else
    printf '\nSTAGING_DOMAIN=%s\n' "$1" >> .env.prod
  fi
  grep -c '^STAGING_DOMAIN=' .env.prod; grep '^STAGING_DOMAIN=' .env.prod   # ровно одна строка
}
# дальше — только если функция определена и STAGING_DOMAIN действительно очищен
command -v set_staging_domain >/dev/null || { echo "set_staging_domain не определена — стоп"; exit 1; }
set_staging_domain '' && grep -qx 'STAGING_DOMAIN=' .env.prod || { echo "STAGING_DOMAIN не очищен — стоп"; exit 1; }
docker compose -f docker-compose.prod.yml up -d --no-deps --force-recreate nginx
docker compose -f docker-compose.prod.yml logs nginx | grep "\[staging\]"   # STAGING_DOMAIN не задан
docker compose -f docker-compose.prod.yml exec nginx certbot delete --cert-name staging.<DOMAIN> --non-interactive

# 3. фаервол
ufw delete allow 17881/tcp
ufw delete allow 17882/udp
ufw delete allow 13478/udp
ufw delete allow from 172.16.0.0/12 to any port 17880,15349 proto tcp

# 4. каталог staging (в app/ — логи импорта, рядом .env.staging с ключами)
rm -rf /srv/profichat-staging-src
```

5. DNS: удалить `staging.`, `files.staging.`, `rtc.staging.`, `turn.staging.<DOMAIN>`.

Сеть `profichat-edge` остаётся (её создаёт и использует прод-nginx; пустая — безвредна).
Образ staging-MinIO удалить: `docker image rm profichat-staging/minio:<релиз>`. Образ
`profichat/minio:<релиз>` — прода, не трогать.

---

## B. Прод: деплой и первый полный импорт

### B1. Деплой

DNS, фаервол и `.env.prod` — раздел 0. Затем:

```bash
git checkout HEAD -- nginx docker-compose.prod.yml   # если в A2 nginx обновлялся частичным checkout-ом
git pull
docker compose -f docker-compose.prod.yml up -d --build
```

nginx подключается к сети `profichat-edge` — её создаёт сам compose прода (вручную не
создавать, A2). `STAGING_DOMAIN` в `.env.prod` остаётся, пока работает staging (до A9);
пустой — nginx как без staging. Команды B–D выполняются **в каталоге прода** с
`-f docker-compose.prod.yml`, staging (если запущен) они не затрагивают.

Миграции применяются при старте backend. GetStream-код на месте: **старое приложение
работает как раньше** (сообщения, звонки, пуши Stream). Проверки — как A5 (с доменом прода и `-f docker-compose.prod.yml`).

`MESSENGER_LEGACY_MODE=True` (по умолчанию, раздел 0.3): `shouldReply` и порядок чатов в
`GET /api/chats/` — как раньше, по GetStream и дате создания; приветствие не шлёт второй пуш.
Новые поля списка (`lastMessage`, `lastMessageAt`, `unreadCount`) старое приложение не
читает; они отстают от Stream, пока не прошёл импорт (и между импортами).

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

Одновременно выключить переходный режим: `shouldReply` и порядок чатов — из нашей базы,
приветствие — с нашим пушем (раздел 0.3):

```bash
sed -i 's/^MESSENGER_LEGACY_MODE=.*/MESSENGER_LEGACY_MODE=False/' .env.prod
grep -q '^MESSENGER_LEGACY_MODE=' .env.prod || printf '\nMESSENGER_LEGACY_MODE=False\n' >> .env.prod
docker compose -f docker-compose.prod.yml up -d backend celery celery-beat
docker compose -f docker-compose.prod.yml exec backend python manage.py shell -c \
  "from django.conf import settings; print(settings.MESSENGER_LEGACY_MODE)"   # False
```

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

Повторный импорт **никогда не перетирает то, что пользователь сделал в новом приложении**:
закрепление чата из Stream не применяется, если участник хоть раз закреплял/откреплял чат у
нас (`ChatMember.pin_changed_at`), а позиция «прочитано» из Stream — если он отмечал
прочитанным или непрочитанным (`ChatMember.read_changed_at`; `unreadCount` при этом
пересчитывается). Для остальных участников импорт, как и раньше, двигает «прочитано» только
вперёд и переносит закрепление, только если у нас чат не закреплён.

### C4. Сверка количества по каналам

Сумма из финального прогона — первый сигнал. Затем — по каналам: независимый подсчёт в
Stream (скрипт из A6) против нашей базы:

```bash
docker compose -f docker-compose.prod.yml exec backend python manage.py shell -c "
from messenger.models import Message
CID = 'chat_12_34'
qs = Message.objects.filter(chat__channel_id=CID, stream_id__isnull=False)
print(CID, 'imported:', qs.count(), 'deleted:', qs.filter(deleted_at__isnull=False).count())
"
```

Для точного расхождения — сравнить множества id (`ids` из скрипта A6 против
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
