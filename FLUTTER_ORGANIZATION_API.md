# Organization Profile API — Flutter Integration Guide

## Новые эндпоинты

| Метод | URL | Описание |
|-------|-----|----------|
| `GET` | `/api/organizations/` | Список организаций (без изменений) |
| `GET` | `/api/organizations/{id}/` | **НОВЫЙ** — полный профиль организации |
| `GET` | `/api/organizations/{id}/specialists/` | **НОВЫЙ** — специалисты организации |

---

## GET `/api/organizations/{id}/`

Полный профиль организации.

### Response

```json
{
  "id": 1,
  "name": "Adam.Tech",
  "logo": "https://example.com/media/organizations/logos/logo.png",
  "category": "IT-компания",
  "description": "Lorem ipsum dolor sit amet consectetur...",
  "rating": "4.8",
  "reviews_count": 12,
  "addresses": [
    {
      "id": 1,
      "address": "ул. Абдрахманова, 123, Бишкек",
      "is_primary": true
    },
    {
      "id": 2,
      "address": "ул. Манаса, 45, Бишкек",
      "is_primary": false
    }
  ],
  "work_schedules": [
    {
      "id": 1,
      "day_of_week": 1,
      "day_of_week_display": "Понедельник",
      "from_time": "10:00:00",
      "to_time": "20:00:00",
      "is_day_off": false,
      "is_round_the_clock": false
    },
    {
      "id": 6,
      "day_of_week": 6,
      "day_of_week_display": "Суббота",
      "from_time": null,
      "to_time": null,
      "is_day_off": true,
      "is_round_the_clock": false
    }
  ],
  "social_links": [
    {
      "id": 1,
      "social_network": {
        "id": 1,
        "name": "Instagram",
        "logo": "https://example.com/media/social_networks/logos/instagram.png"
      },
      "url": "adam.tech.company"
    }
  ],
  "services": [
    { "id": 1, "name": "Разработка веб-сайтов" },
    { "id": 2, "name": "CRM системы" },
    { "id": 3, "name": "ИИ" }
  ],
  "gallery_images": [
    {
      "id": 1,
      "image": "https://example.com/media/organizations/gallery/img1.jpg",
      "order": 0
    },
    {
      "id": 2,
      "image": "https://example.com/media/organizations/gallery/img2.jpg",
      "order": 1
    }
  ]
}
```

### Поля

| Поле | Тип | Описание |
|------|-----|----------|
| `id` | int | ID организации |
| `name` | string | Название |
| `logo` | string \| null | URL логотипа |
| `category` | string \| null | Тип компании, например "IT-компания" |
| `description` | string \| null | Описание компании |
| `rating` | string | Рейтинг от 0.0 до 5.0 |
| `reviews_count` | int | Количество отзывов |
| `addresses` | array | Адреса (см. ниже) |
| `work_schedules` | array | График работы (см. ниже) |
| `social_links` | array | Соцсети (см. ниже) |
| `services` | array | Услуги/теги |
| `gallery_images` | array | Галерея, отсортирована по `order` |

#### addresses[]

| Поле | Тип | Описание |
|------|-----|----------|
| `id` | int | |
| `address` | string | Полный адрес |
| `is_primary` | bool | `true` — главный адрес (показывать первым) |

#### work_schedules[]

Всегда отсортированы по дню недели (Пн=1 → Вс=7).

| Поле | Тип | Описание |
|------|-----|----------|
| `day_of_week` | int | 1=Пн, 2=Вт, 3=Ср, 4=Чт, 5=Пт, 6=Сб, 7=Вс |
| `day_of_week_display` | string | Человекочитаемое название дня |
| `from_time` | string \| null | Время начала, формат `"HH:MM:SS"` |
| `to_time` | string \| null | Время окончания, формат `"HH:MM:SS"` |
| `is_day_off` | bool | `true` — выходной день |
| `is_round_the_clock` | bool | `true` — работает круглосуточно |

> Если `is_day_off = true` — показывать "выходной", игнорировать `from_time`/`to_time`.  
> Если `is_round_the_clock = true` — показывать "круглосуточно".

#### social_links[]

| Поле | Тип | Описание |
|------|-----|----------|
| `social_network.id` | int | |
| `social_network.name` | string | Название платформы, например "Instagram" |
| `social_network.logo` | string \| null | URL иконки платформы |
| `url` | string | Username или ссылка |

#### gallery_images[]

| Поле | Тип | Описание |
|------|-----|----------|
| `image` | string | URL изображения |
| `order` | int | Порядок отображения (уже отсортированы) |

---

## GET `/api/organizations/{id}/specialists/`

Список специалистов организации. Возвращает только пользователей с ролью `specialist`.

### Response

```json
[
  {
    "id": 42,
    "first_name": "Эмирлан",
    "last_name": "Шайбеков",
    "middle_name": null,
    "photo": "https://example.com/media/user/photos/2024/01/01/photo.jpg",
    "profession": {
      "id": 3,
      "name": "Co-founder"
    }
  },
  {
    "id": 43,
    "first_name": "Дастанбек",
    "last_name": "Азимжанов",
    "middle_name": null,
    "photo": "https://example.com/media/user/photos/2024/01/01/photo2.jpg",
    "profession": {
      "id": 3,
      "name": "Co-founder"
    }
  }
]
```

### Поля

| Поле | Тип | Описание |
|------|-----|----------|
| `id` | int | ID пользователя |
| `first_name` | string | Имя |
| `last_name` | string | Фамилия |
| `middle_name` | string \| null | Отчество |
| `photo` | string \| null | URL фото |
| `profession` | object \| null | `{ id, name }` — профессия/должность |

---

## Изменения в `GET /api/organizations/` (список)

Список организаций **не изменился**. Возвращает те же поля: `id`, `name`, `logo`, `description`, `rating`.
