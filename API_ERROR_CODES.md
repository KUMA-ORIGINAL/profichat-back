# Коды ошибок API

Любая ошибка, которую возвращает бэкенд, содержит поле `code` — машинночитаемый
код ошибки. Клиент принимает решения **по `code`**, а не по тексту сообщения и не
по HTTP-статусу: текст может измениться, статус слишком общий.

## Формат ответа с ошибкой

```json
{
  "code": "OTP_CODE_INVALID",
  "message": "Неверный код",
  "detail": "Неверный код",
  "errors": { "phone_number": ["Обязательное поле."] }
}
```

| Поле      | Всегда | Описание                                                                        |
|-----------|--------|---------------------------------------------------------------------------------|
| `code`    | да     | Код ошибки из таблицы ниже                                                      |
| `message` | да     | Человекочитаемое сообщение — можно показать пользователю                         |
| `detail`  | да     | Дубль `message`, оставлен для старых клиентов                                    |
| `errors`  | нет    | Разбор по полям (ошибки валидации) или тело ошибки внешней системы               |

Плюс поля конкретной ошибки: например `secondsLeft` и `channel` у таймеров OTP,
`param` у ошибок параметров запроса.

Ответы отдаются в camelCase, поэтому на клиенте это `code`, `message`, `detail`,
`errors`, `secondsLeft`.

## Обратная совместимость

Ничего из старого формата не удалено — только добавлены `code` и `message`:

- 401 по-прежнему содержит `error: "Unauthorized"` и `reason`
  (`token_expired` / `logged_in_from_another_device` / `invalid_token`);
- ошибки валидации по-прежнему содержат поля на верхнем уровне
  (`{"phoneNumber": ["Обязательное поле."]}`), причём **первыми** в теле ответа —
  клиент, который берёт первую ошибку из ответа, получит ошибку поля, а не `code`;
- `detail` сохраняет исходную форму там, где она была не строкой
  (например, ошибки NewCRM: `detail` — список объектов `{msg, type}`);
- доп. поля (`secondsLeft`, `channel`, `valid`, `success`, `error`) на своих местах;
- HTTP-статусы не изменились.

Единственное, что может помешать старому клиенту: если он разбирает **всё тело**
ошибки как «карту полей» (`Map<String, List<String>>`) — в теле теперь есть строковые
значения `code` / `message` / `detail`. Читайте поля через `errors`, а не через всё тело.

## Как обрабатывать на клиенте

```dart
switch (error.code) {
  case 'OTP_SEND_COOLDOWN':
  case 'OTP_SMS_RESEND_COOLDOWN':
    startTimer(error.secondsLeft);
    break;
  case 'OTP_CODE_INVALID':
    showFieldError(codeField, error.message);
    break;
  case 'TOKEN_REVOKED':
    logoutWithMessage(error.message);   // вошли с другого устройства
    break;
  case 'TOKEN_EXPIRED':
    refreshTokenAndRetry();
    break;
  default:
    showSnackbar(error.message);        // незнакомый код — показываем текст
}
```

Незнакомый `code` — всегда безопасный fallback: показать `message`.

## Общие коды

| Код                      | HTTP | Когда                                                        |
|--------------------------|------|--------------------------------------------------------------|
| `VALIDATION_ERROR`       | 400  | Ошибки валидации, разбор по полям — в `errors`                |
| `PARSE_ERROR`            | 400  | Тело запроса не разобрано (битый JSON)                       |
| `PARAM_REQUIRED`         | 400  | Не передан обязательный параметр (`param` — какой именно)     |
| `PARAM_INVALID`          | 400  | Параметр передан в неверном формате (`param` — какой именно)   |
| `NOT_AUTHENTICATED`      | 401  | Нет токена / требуется авторизация                            |
| `PERMISSION_DENIED`      | 403  | Недостаточно прав                                            |
| `NOT_FOUND`              | 404  | Объект не найден                                             |
| `METHOD_NOT_ALLOWED`     | 405  | Метод не поддерживается эндпоинтом                            |
| `NOT_ACCEPTABLE`         | 406  | Неподдерживаемый `Accept`                                    |
| `UNSUPPORTED_MEDIA_TYPE` | 415  | Неподдерживаемый `Content-Type`                              |
| `CONFLICT`               | 409  | Конфликт состояния                                           |
| `THROTTLED`              | 429  | Слишком много запросов (rate limit)                          |
| `INTERNAL_ERROR`         | 500  | Внутренняя ошибка сервера                                    |
| `SERVICE_UNAVAILABLE`    | 503  | Сервис временно недоступен                                   |
| `UPSTREAM_ERROR`         | 502  | Ошибка внешнего сервиса                                      |

## Авторизация и токены

| Код                     | HTTP | Когда                                            | Что делать клиенту               |
|-------------------------|------|--------------------------------------------------|----------------------------------|
| `TOKEN_EXPIRED`         | 401  | Срок действия access-токена истёк                | Обновить токен и повторить запрос |
| `TOKEN_REVOKED`         | 401  | Токен в блэклисте — вход с другого устройства     | Разлогинить, показать `message`   |
| `TOKEN_INVALID`         | 401  | Некорректный токен                               | Разлогинить                      |
| `NOT_AUTHENTICATED`     | 401  | Токен не передан                                 | Экран входа                      |
| `INVALID_CREDENTIALS`   | 400  | Неверный номер телефона или пароль               | Показать ошибку в форме          |
| `ACCOUNT_NOT_ACTIVATED` | 400  | Аккаунт не активирован                           | Показать `message`               |

В ответах 401 дополнительно приходят legacy-поля `error: "Unauthorized"` и
`reason` (`token_expired` / `logged_in_from_another_device` / `invalid_token`).

## OTP (вход по коду)

| Код                       | HTTP | Когда                                        | Доп. поля                 |
|---------------------------|------|----------------------------------------------|---------------------------|
| `OTP_SEND_COOLDOWN`       | 429  | Новый код запрошен раньше, чем через минуту   | `secondsLeft`             |
| `OTP_SMS_RESEND_COOLDOWN` | 429  | Повтор по SMS раньше, чем через минуту        | `secondsLeft`, `channel`  |
| `OTP_SEND_FAILED`         | 400  | Провайдер отклонил номер (ответил 4xx)        | —                         |
| `OTP_SEND_FAILED`         | 502  | Провайдер недоступен или ответил 5xx          | —                         |
| `OTP_CODE_INVALID`        | 400  | Неверный код                                 | —                         |
| `OTP_CODE_EXPIRED`        | 400  | Код просрочен (живёт 5 минут)                 | —                         |

Подробнее про сценарий WhatsApp → SMS: [OTP_SMS_FALLBACK_API.md](OTP_SMS_FALLBACK_API.md).

## Чаты

| Код                            | HTTP | Когда                                              |
|--------------------------------|------|----------------------------------------------------|
| `CHAT_NOT_FOUND`               | 404  | Чат не найден или недоступен текущему пользователю   |
| `SPECIALIST_ONLY`              | 403  | Действие доступно только специалисту                |
| `CHAT_CHANNEL_MISMATCH`        | 400  | Чат уже существует с другим `channel_id`             |
| `STREAM_CHANNEL_CREATE_FAILED` | 400  | Не удалось создать канал в GetStream                |
| `STREAM_CHANNEL_UPDATE_FAILED` | 400  | Не удалось обновить канал в GetStream               |

## Тарифы, доступы, оплата

| Код                        | HTTP | Когда                                                     |
|----------------------------|------|-----------------------------------------------------------|
| `TARIFF_NOT_FOUND`         | 400/404 | Тариф не найден или не принадлежит специалисту          |
| `FREE_TARIFF_ACTIVE`       | 400  | Бесплатный тариф этого специалиста ещё активен             |
| `FREE_TARIFF_ALREADY_USED` | 400  | Бесплатный тариф у этого специалиста уже был использован   |
| `PAYMENT_LINK_FAILED`      | 500  | Не удалось сформировать ссылку на оплату                  |
| `SUBSCRIPTION_NOT_FOUND`   | 404  | По каналу нет подписки                                    |
| `SUBSCRIPTION_NOT_ACTIVE`  | 400  | Отменить можно только активную подписку                    |
| `ACCESS_ORDER_NOT_FOUND`   | 404  | Нет активного доступа к специалисту                       |
| `ORDER_NOT_FOUND`          | 404  | Заказ из webhook платёжной системы не найден              |

## Интеграции (NewCRM / MedCRM / SSO / Telegram)

| Код                            | HTTP    | Когда                                                |
|--------------------------------|---------|------------------------------------------------------|
| `ORGANIZATION_NOT_FOUND`       | 404     | Организация в NewCRM не найдена                       |
| `SPECIALIST_NOT_FOUND`         | 404     | Специалист с таким номером не найден                  |
| `CLIENT_NOT_FOUND`             | 404     | Клиент не найден или с ним нет чата                   |
| `CLIENT_NOT_LINKED_TO_NEWCRM`  | 404     | Клиент не связан с картой в NewCRM                    |
| `CONCLUSION_NOT_FOUND`         | 404     | Заключение не найдено или принадлежит другому клиенту   |
| `NEWCRM_ERROR`                 | 4xx     | NewCRM вернул ошибку (тело — в `errors`)              |
| `NEWCRM_UNAVAILABLE`           | 502/503 | NewCRM недоступен или не настроен                     |
| `SSO_NOT_CONFIGURED`           | 500     | Не настроен `MEDCRM_SSO_WEB_URL`                      |
| `SSO_TOKEN_INVALID`            | 401     | SSO-токен недействителен или уже использован          |
| `PHONE_NUMBER_MISSING`         | 400/401 | У пользователя нет номера телефона                    |
| `INVALID_INTEGRATION_SECRET`   | 403     | Неверный `X-Integration-Secret`                       |
| `INVALID_WEBHOOK_SECRET`       | 403     | Неверный секрет webhook                               |
| `TELEGRAM_SESSION_NOT_FOUND`   | 404     | Сессия входа через Telegram не найдена или истекла     |
| `TELEGRAM_SESSION_ALREADY_USED`| 410     | Сессия входа через Telegram уже использована          |

## Как добавить новый код (бэкенд)

1. Добавить константу в `ErrorCode` — [app/common/errors.py](app/common/errors.py).
2. Вернуть ошибку одним из двух способов:

```python
from common.errors import AppError, ErrorCode, error_response

# из view — готовый Response
return error_response(
    ErrorCode.CHAT_NOT_FOUND,
    "Чат не найден",
    status.HTTP_404_NOT_FOUND,
)

# из сервиса или сериализатора — исключение
raise AppError("Тариф не найден.", code=ErrorCode.TARIFF_NOT_FOUND, status_code=404)
```

3. Описать код в этом файле.

Всё остальное (ошибки валидации DRF, 401/403/404/405, необработанные исключения)
получает код автоматически в `common.error_handler.api_exception_handler`, так что
ответа без `code` не бывает.
