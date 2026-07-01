# REST API — интерфейс аналитика (Шаг 5)

API для работы аналитика с алертами: список, детали «почему сработало»,
смена статуса, сводка для дашборда. Бэкенд: Django + Django REST Framework.

- **Базовый URL (разработка):** `http://localhost:8000`
- **Интерактивная документация (Swagger UI):** `http://localhost:8000/api/docs/`
- **OpenAPI-схема (YAML):** `http://localhost:8000/api/schema/`
- **CORS:** на время разработки разрешены любые источники `http://localhost:<порт>`
  и `http://127.0.0.1:<порт>` (React-фронтенд на другом порту работает без настройки).

## Важно про денежные суммы (wei)

Все суммы в Ethereum хранятся в **wei** (1 ETH = 10¹⁸ wei) — это огромные целые
числа. Они **отдаются строками**, а не числами: обычный `number` в JavaScript не
вмещает такие значения без потери точности.

Это касается полей: `amount`, `gas_fee`, `total_received`, `total_sent`.
Баллы риска (`final_score`, `risk_score`) — небольшие, отдаются числами.

## Паг(Пагинация)

Стиль `limit/offset` (DRF `LimitOffsetPagination`).

| Параметр | По умолчанию | Описание |
|----------|--------------|----------|
| `limit`  | 50           | сколько записей вернуть |
| `offset` | 0            | сколько пропустить |

Ответ-список всегда обёрнут: `{ "count", "next", "previous", "results": [...] }`.

---

## GET /api/alerts/ — список алертов

Сортировка по умолчанию: свежие сверху (`created_at` по убыванию).

### Query-параметры

| Параметр | Значения | Описание |
|----------|----------|----------|
| `status` | `open` / `in_progress` / `closed` / `false_positive` | фильтр по статусу |
| `level` | `low` / `medium` / `high` | фильтр по уровню |
| `target_type` | `transaction` / `wallet` | фильтр по типу цели |
| `ordering` | `created_at`, `-created_at`, `level`, `status` | сортировка |
| `limit`, `offset` | | пагинация |

### Пример

```
GET /api/alerts/?status=open&level=high&limit=2
```

```json
{
  "count": 37,
  "next": "http://localhost:8000/api/alerts/?level=high&limit=2&offset=2&status=open",
  "previous": null,
  "results": [
    {
      "id": 13,
      "target_type": "transaction",
      "level": "high",
      "status": "open",
      "title": "Рискованная транзакция: HIGH (70.00)",
      "description": "Сработавшие правила: Большая сумма (+30.00); Связь с миксером (+40.00)",
      "created_at": "2026-06-27T15:40:34.706422Z",
      "resolved_at": null,
      "final_score": 70.0
    }
  ]
}
```

`final_score` берётся из связанной оценки риска (`transaction_risk` или `wallet_risk`).

---

## GET /api/alerts/{id}/ — детали алерта

К полям списка добавляются `risk_level`, `fired_rules` (сработавшие правила с
баллами) и `context` — подробности объекта, к которому относится алерт.

### Алерт по транзакции (`target_type = "transaction"`)

```
GET /api/alerts/13/
```

```json
{
  "id": 13,
  "target_type": "transaction",
  "level": "high",
  "status": "open",
  "title": "Рискованная транзакция: HIGH (70.00)",
  "description": "Сработавшие правила: Большая сумма (+30.00); Связь с миксером (+40.00)",
  "created_at": "2026-06-27T15:40:34.706422Z",
  "resolved_at": null,
  "final_score": 70.0,
  "risk_level": "HIGH",
  "fired_rules": [
    { "name": "Большая сумма", "score": 30.0 },
    { "name": "Связь с миксером", "score": 40.0 }
  ],
  "context": {
    "tx_hash": "0x9b629147b75dc0b275d478fa34d97c5d4a26926457540b15a5ce871df36c23fd",
    "amount": "250000000000000000",
    "gas_fee": "1050000000000000",
    "currency": "ETH",
    "sender_address": "0x1db3439a222c519ab44bb1144fc28167b4fa6ee6",
    "receiver_address": "0xd8da6bf26964af9d7eed9e03e53415d37aa96045",
    "block_number": 302086,
    "transaction_timestamp": "2015-09-28T08:24:43Z",
    "status": "success"
  }
}
```

### Алерт по кошельку (`target_type = "wallet"`)

`context` для кошелька выглядит так:

```json
{
  "context": {
    "address": "0xd8da6bf26964af9d7eed9e03e53415d37aa96045",
    "transaction_count": 15,
    "total_received": "250000000000000002",
    "total_sent": "2570000000000000",
    "risk_score": 60.0,
    "is_flagged": true,
    "label": null,
    "first_seen_at": "2015-09-28T08:24:43Z",
    "last_seen_at": "2015-10-04T12:00:00Z"
  }
}
```

### Ошибка

```
GET /api/alerts/99999/   ->   404
{ "detail": "No Alert matches the given query." }
```

---

## PATCH /api/alerts/{id}/status/ — смена статуса

Тело запроса:

```json
{ "status": "in_progress" }
```

### Допустимые переходы

```
open ──► in_progress ──► closed
             │      └───► false_positive
             └──► open   (откат в работу)
```

`closed` и `false_positive` — терминальные. При переходе в них автоматически
проставляется `resolved_at = now()`.

### Успех

```
PATCH /api/alerts/13/status/   { "status": "in_progress" }   ->   200
```

Возвращает обновлённый алерт в формате деталей (как `GET /api/alerts/{id}/`).

### Ошибки (400) — понятные сообщения

| Ситуация | Ответ |
|----------|-------|
| Недопустимый переход | `{ "detail": "Недопустимый переход 'open' → 'closed'. Из 'open' можно перейти в: in_progress." }` |
| Из терминального статуса | `{ "detail": "Из статуса 'closed' переходы запрещены (терминальный статус)." }` |
| Неизвестное значение | `{ "detail": "Не передан корректный статус.", "errors": { "status": ["\"banana\" is not a valid choice."] } }` |

---

## GET /api/stats/ — сводка для дашборда

```
GET /api/stats/
```

```json
{
  "total_alerts": 40,
  "alerts_last_24h": 6,
  "by_status": {
    "open": 30,
    "in_progress": 4,
    "closed": 4,
    "false_positive": 2
  },
  "by_level": {
    "low": 0,
    "medium": 30,
    "high": 6,
    "critical": 4
  },
  "flagged_wallets": 3,
  "trend": [0, 1, 0, 3, 2, 5, 4, 6, 2, 1, 0, 3, 8, 6]
}
```

| Поле | Описание |
|------|----------|
| `total_alerts` | всего алертов |
| `alerts_last_24h` | создано за последние сутки |
| `by_status` | число алертов по каждому статусу (все 4 ключа всегда присутствуют) |
| `by_level` | разбивка по уровням: `low`/`medium`/`high`/`critical` (все ключи всегда присутствуют) |
| `flagged_wallets` | число помеченных кошельков (`wallet.is_flagged = true`) |
| `trend` | число алертов по дням за 14 дней (массив из 14 чисел, старое → новое) |

> Дашборд берёт числа из `/api/stats/` (агрегаты считает сервер) — фронтенду не нужно
> грузить все алерты, поэтому дашборд остаётся быстрым и точным при пагинации.

---

## Пагинация списков

`/api/alerts/`, `/api/wallets/`, `/api/transactions/` пагинируются одинаково
(`limit`/`offset`) и возвращают `{ count, next, previous, results }` — сервер никогда
не отдаёт всю таблицу разом. Интерфейс грузит первую страницу (100 записей) и
подгружает следующие кнопкой «Показать ещё». `/api/rules/` не пагинируется (правил мало).

---

## Как запустить сервер

```powershell
python -m pip install -r requirements.txt
python manage.py migrate          # создаёт только служебные таблицы Django
python manage.py runserver        # http://localhost:8000
```

Документация откроется на `http://localhost:8000/api/docs/`.

> База данных — та же, что у сбора данных (`DATABASE_URL` из `.env`). Наши 7 таблиц
> описаны моделями с `managed = False`: Django их не создаёт и не меняет, источник
> истины — `db/schema.sql`.
