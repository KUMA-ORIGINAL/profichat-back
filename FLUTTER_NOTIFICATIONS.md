# Уведомления: что открывать по нажатию — инструкция для Flutter

Каждое уведомление несёт два признака, и они отвечают на разные вопросы:

| Поле | Вопрос | Значения |
|---|---|---|
| `source` | **чьё** это событие | `profichat` \| `erkinai` |
| `type` (`notificationType` в ленте) | **что** случилось | `system`, `payment_success`, `chat_invite`, `application_accepted`, `application_rejected`, `erkinai` |

Ветвитесь сначала по `source`, потом по `type`. `source` — узкий закрытый
список из двух значений, он не будет расти; `type` пополняется по мере
появления новых сценариев, и приложение должно переживать незнакомый тип, не
падая (показать заголовок и текст, открыть общий экран уведомлений).

Оба признака приходят **и в ленте, и в push** — специально: push доходит не
всегда, а лента не будит приложение.

## Лента

```
GET /api/notifications/
```

```json
{
  "id": 101,
  "source": "profichat",
  "notificationType": "chat_invite",
  "title": "Новый чат",
  "message": "Вас пригласили в чат со специалистом",
  "payload": {
    "source": "profichat",
    "type": "chat_invite",
    "chatId": "42",
    "channelId": "chat_15_7",
    "senderId": "7"
  },
  "isRead": false,
  "readAt": null,
  "createdAt": "2026-03-23T21:00:00+06:00"
}
```

Рядом: `GET /api/notifications/unread-count/`,
`POST /api/notifications/<id>/mark-read/`, `POST /api/notifications/mark-read/`.

## Push

В `data`-блоке FCM приходит **тот же `payload`**, включая `source` и `type`.
Все значения — строки (ограничение FCM), числа приводятся к строкам: `"42"`,
а не `42`.

`notification` (title/body) FCM показывает сам; `data` — то, по чему приложение
решает, куда вести.

## Что делать по source

### `source: "profichat"` — своё событие

Открывается внутри приложения. Ориентируйтесь на `type`:

| `type` | Что открыть | Что в `payload` |
|---|---|---|
| `chat_invite` | чат | `chatId`, `channelId`, `senderId` |
| `payment_success` | экран тарифа/оплаты | `order_id` |
| `application_accepted` / `application_rejected` | заявка | зависит от сценария |
| `system` | общий экран уведомлений | — |

### `source: "erkinai"` — событие из CRM

Породила клиника: напоминание о приёме, отмена записи, готовое заключение.
Ведёт в раздел ErkinAI, а не во внутренние экраны ProfiChat.

```json
{
  "source": "erkinai",
  "type": "erkinai",
  "event": "appointment.created",
  "organizationId": "4",
  "external_id": "automation-job-812"
}
```

* `event` — код события CRM (`appointment.created`, `appointment.cancelled`
  и т.п.). По нему выбирайте экран. Список кодов растёт вместе с автоматизациями
  в CRM, поэтому незнакомый `event` — не ошибка: покажите текст уведомления и
  общий экран.
* `organizationId` — клиника, которая это прислала.
* `external_id` — служебный идентификатор отправки, для приложения бесполезен.

**Персональных данных в push нет и не будет.** CRM намеренно не кладёт в
`payload` содержимое события — ни имени пациента, ни телефона, ни диагноза:
`data`-блок FCM проходит через Google и лежит на устройстве открытым текстом.
Детали приложение подтягивает своими вызовами после нажатия — историю приёмов
через `GET /api/integration/newcrm/appointments/`, заключение через
`GET /api/integration/newcrm/conclusions/<id>/`.

## Чего ждать в реальности

* Push может не дойти вовсе: устройство не зарегистрировано, токен протух,
  уведомления запрещены. Экран уведомлений строится **на ленте**; push только
  будит приложение и даёт `payload` для перехода.
* Проверить доставку на конкретных устройствах: `GET /api/push/status/` —
  последний успех/провал и код ошибки FCM по каждому.
* Токен регистрируется через `POST /api/register-fcm/`.
