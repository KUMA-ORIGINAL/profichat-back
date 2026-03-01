# Profigram API — Интеграция с MedCRM

## Авторизация

Все запросы требуют заголовок:

```
X-Api-Key: <ваш ключ>
```

Ключ получите у администратора Profigram. Храните его **только на сервере**, не передавайте на фронтенд.

---

## Базовый URL

```
https://<domain>/api/integration/medcrm
```

---

## 1. Получить тарифы специалиста

Возвращает список активных тарифов специалиста по номеру телефона.

### Запрос

```
GET /api/integration/medcrm/tariffs/?phone_number=+996700123456
```


| Параметр       | Тип    | Обязательный | Описание                                  |
| -------------- | ------ | ------------ | ----------------------------------------- |
| `phone_number` | string | да           | Номер телефона специалиста (формат +996…) |


### Заголовки

```
X-Api-Key: <ключ>
```

### Ответ — `200 OK`

```json
[
  {
    "id": 1,
    "name": "Консультация 30 мин",
    "price": "0.00",
    "duration_hours": 24,
    "tariff_type": "free",
    "is_active": true
  },
  {
    "id": 2,
    "name": "Пакет на месяц",
    "price": "1500.00",
    "duration_hours": 720,
    "tariff_type": "paid",
    "is_active": true
  }
]
```

### Ошибки


| Код | Тело                                                  | Причина                       |
| --- | ----------------------------------------------------- | ----------------------------- |
| 400 | `{"detail": "Параметр phone_number обязателен."}`     | Не передан номер телефона     |
| 401 | `{"detail": "Неверный API-ключ."}`                    | Неверный или отсутствует ключ |
| 404 | `{"detail": "Специалист с таким номером не найден."}` | Нет такого специалиста        |


---

## 2. Пригласить клиента

Создаёт приглашение клиента от имени специалиста. Если клиент новый — ему придёт SMS со ссылкой на регистрацию. Если клиент уже зарегистрирован — он получит push-уведомление.

### Запрос

```
POST /api/integration/medcrm/invite-client/
Content-Type: application/json
X-Api-Key: <ключ>
```

### Тело запроса

```json
{
  "specialist_phone_number": "+996700123456",
  "client_phone_number": "+996700654321",
  "tariff_id": 1,
  "note": "Пациент Иванов, первичный приём"
}
```


| Поле                      | Тип    | Обязательный | Описание                                  |
| ------------------------- | ------ | ------------ | ----------------------------------------- |
| `specialist_phone_number` | string | да           | Номер телефона специалиста (формат +996…) |
| `client_phone_number`     | string | да           | Номер телефона клиента (формат +996…)     |
| `tariff_id`               | int    | да           | ID тарифа (из эндпоинта выше)             |
| `note`                    | string | нет          | Заметка специалиста о клиенте             |


### Ответ — `201 Created`

```json
{
  "chat_id": 42,
  "channel_id": "chat_15_3",
  "client_id": 15,
  "is_new_client": true,
  "invite_delivery": {
    "id": 105,
    "created_at": "2026-03-01T10:12:45Z",
    "channel": "sms",
    "status": "sent",
    "provider_status": "0",
    "error_message": "",
    "is_new_client": true
  }
}
```


| Поле            | Тип    | Описание                                  |
| --------------- | ------ | ----------------------------------------- |
| `chat_id`       | int    | ID чата в Profigram                       |
| `channel_id`    | string | ID канала в мессенджере (Stream)          |
| `client_id`     | int    | ID клиента в Profigram                    |
| `is_new_client` | bool   | `true` — клиент создан, `false` — уже был |
| `invite_delivery` | object | Результат отправки приглашения (SMS/Push) |

`invite_delivery.status`:

- `sent` — отправлено успешно
- `failed` — ошибка отправки


### Ошибки


| Код | Тело                                                                    | Причина                       |
| --- | ----------------------------------------------------------------------- | ----------------------------- |
| 400 | `{"specialist_phone_number": ["Обязательное поле."]}`                   | Не передано обязательное поле |
| 401 | `{"detail": "Неверный API-ключ."}`                                      | Неверный или отсутствует ключ |
| 404 | `{"detail": "Специалист с таким номером не найден."}`                   | Нет такого специалиста        |
| 404 | `{"detail": "Тариф не найден или не принадлежит данному специалисту."}` | Тариф не найден / чужой тариф |


---

## Подключение из Supabase

API-ключ Profigram **нельзя** хранить на фронте. Все вызовы идут через **Supabase Edge Functions**.

### Схема

```
MedCRM фронт  →  supabase.functions.invoke()  →  Edge Function  →  Profigram API
                                                  (хранит ключ)
```

### Шаг 1. Сохранить API-ключ в Supabase Secrets

```bash
supabase secrets set PROFIGRAM_API_KEY="L8eTVvfXz2071iDJZWVv7zhs3H3gMx3daGU99unH0EP37i6Q3YU0MEvQtK_6RvY1"
```

### Шаг 2. Edge Function — получение тарифов

Создать файл `supabase/functions/profigram-tariffs/index.ts`:

```ts
import { serve } from "https://deno.land/std@0.177.0/http/server.ts";

const PROFIGRAM_BASE = "https://<domain>/api/integration/medcrm";
const API_KEY = Deno.env.get("PROFIGRAM_API_KEY")!;

serve(async (req) => {
  const { searchParams } = new URL(req.url);
  const phone = searchParams.get("phone_number");

  if (!phone) {
    return new Response(
      JSON.stringify({ error: "phone_number is required" }),
      { status: 400, headers: { "Content-Type": "application/json" } },
    );
  }

  const res = await fetch(
    `${PROFIGRAM_BASE}/tariffs/?phone_number=${encodeURIComponent(phone)}`,
    { headers: { "X-Api-Key": API_KEY } },
  );

  const data = await res.json();
  return new Response(JSON.stringify(data), {
    status: res.status,
    headers: { "Content-Type": "application/json" },
  });
});
```

### Шаг 3. Edge Function — приглашение клиента

`supabase/functions/profigram-invite/index.ts`:

Создать файл 

```ts
import { serve } from "https://deno.land/std@0.177.0/http/server.ts";

const PROFIGRAM_BASE = "https://<domain>/api/integration/medcrm";
const API_KEY = Deno.env.get("PROFIGRAM_API_KEY")!;

serve(async (req) => {
  if (req.method !== "POST") {
    return new Response("Method not allowed", { status: 405 });
  }

  const body = await req.json();

  const res = await fetch(`${PROFIGRAM_BASE}/invite-client/`, {
    method: "POST",
    headers: {
      "X-Api-Key": API_KEY,
      "Content-Type": "application/json",
    },
    body: JSON.stringify(body),
  });

  const data = await res.json();
  return new Response(JSON.stringify(data), {
    status: res.status,
    headers: { "Content-Type": "application/json" },
  });
});
```

### Шаг 4. Деплой

```bash
supabase functions deploy profigram-tariffs
supabase functions deploy profigram-invite
```

### Шаг 5. Вызов с фронтенда MedCRM

```ts
import { createClient } from "@supabase/supabase-js";

const supabase = createClient(SUPABASE_URL, SUPABASE_ANON_KEY);

// Получить тарифы
const { data: tariffs } = await supabase.functions.invoke(
  "profigram-tariffs",
  { body: null, headers: { phone_number: "+996700123456" } },
);
// Или через query string:
// GET https://<project>.supabase.co/functions/v1/profigram-tariffs?phone_number=+996700123456

// Пригласить клиента
const { data: invite } = await supabase.functions.invoke(
  "profigram-invite",
  {
    body: {
      specialist_phone_number: "+996700123456",
      client_phone_number: "+996700654321",
      tariff_id: 1,
      note: "Пациент Иванов",
    },
  },
);
```

---

## Типичный сценарий использования

```
1. Специалист в MedCRM нажимает «Пригласить в Profigram»
2. Фронт → Edge Function profigram-tariffs → Profigram GET /tariffs/
3. Специалист выбирает тариф из списка
4. Фронт → Edge Function profigram-invite → Profigram POST /invite-client/
5. Клиент получает SMS (новый) или push (существующий) → переходит в Profigram
```

---

## Формат номера телефона

Все номера передавать в международном формате: `+996XXXXXXXXX`