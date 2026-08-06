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
    "last_seen_at": "2015-10-04T12:00:00Z",

    "rule_score": 0.0,
    "ml_score": 65.0,
    "ml_explanation": "транзитность=0.95 (аномально высокий); ...",
    "graph_score": 76.04,
    "graph_explanation": "прямая связь с рисковыми узлами: 1 (миксер/санкции), доля 50%"
  }
}
```

`graph_score` — оценка Graph Analysis (0–100, `null`, если граф ещё не посчитан
командой `--build-graph`); `graph_explanation` — какие граф-метрики её подняли.

---

## GET /api/wallets/{id}/ — детали кошелька

Кроме полей списка отдаёт признаки поведения (`features` → вход ML), граф-признаки
(`graph_features` → положение в сети переводов) и последнюю оценку риска:

```json
{
  "address": "0x53c9293f03b3709e040f1d4bab7bf3968fc93c24",
  "risk_score": 20.0,
  "features": { "tx_total": 10, "unique_counterparties": 4, "transit_ratio": 0.87, "...": "..." },
  "graph_features": {
    "in_degree": 0,
    "out_degree": 1,
    "degree_centrality": 1.5e-05,
    "risky_neighbors": 1,
    "risky_neighbor_ratio": 1.0,
    "transit_ratio": 0.0,
    "fan_in_ratio": 0.0,
    "fan_out_ratio": 0.1,
    "graph_score": 75.9,
    "graph_explanation": "прямая связь с рисковыми узлами: 1 (миксер/санкции), доля 100%",
    "computed_at": "2026-07-26T09:57:07Z"
  },
  "latest_risk": {
    "rule_score": 20.0,
    "ml_score": 65.0,
    "graph_score": 75.9,
    "final_score": 38.0,
    "risk_level": "MEDIUM",
    "ml_explanation": "...",
    "graph_explanation": "прямая связь с рисковыми узлами: 1 (миксер/санкции), доля 100%",
    "decision": {
      "level": "MEDIUM",
      "confidence": 0.6,
      "reasons": ["Граф: подозрительное положение в сети 76% — ..."],
      "sources": {
        "graph": { "score": 75.9, "high": true, "available": true, "explanation": "..." },
        "independent_high_sources": ["graph"]
      }
    }
  }
}
```

`features` и `graph_features` равны `null`, если для кошелька они ещё не посчитаны.

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

## POST /api/screen/ — скрининг адреса по запросу

Проверка **произвольного** Ethereum-адреса, которого может не быть в базе вообще.
В отличие от остальных эндпоинтов, этот не выбирает данные, а **добывает** их:
идёт в Etherscan, сохраняет историю, считает признаки, ML, граф и выдаёт вердикт
Decision Engine. Поэтому запрос идёт **секунды**, а не миллисекунды.

### Тело запроса

```json
{ "address": "0x8589427373d6d84e98730d7795d8f6f8731fdb79", "force": false }
```

`force: true` игнорирует кэш и заново обращается к Etherscan.

### Что происходит внутри

1. Валидация формата (`0x` + 40 hex) — иначе **400** с понятным сообщением.
2. Кэш: если адрес проверялся в последние `SCREEN_CACHE_MINUTES`, отдаётся
   сохранённый результат с `cached: true` и временем последней проверки.
3. Если адреса нет в базе или у него меньше `SCREEN_MIN_TX_FOR_FRESH` транзакций —
   history подтягивается из Etherscan (до `SCREEN_MAX_TX` транзакций).
4. Применяется метка из сид-листа (санкции/миксер/биржа), если адрес там есть.
5. Считаются признаки поведения, ML-аномалия и граф-метрики (локально по эго-сети,
   без пересборки всего графа).
6. Оценка выполняется **тем же** `engine.score_one_wallet`, что и пакетный расчёт —
   вердикт скрининга совпадает с тем, что система скажет об этом кошельке обычным путём.

### Ответ

```json
{
  "address": "0x098b716b8aaf21512996dc57eb0615e2383e2f96",
  "found": true, "no_activity": false,
  "label": "sanctioned", "label_source": "ofac_sdn",
  "risk_level": "CRITICAL", "confidence": 0.99,
  "reasons": [
    "Санкционный адрес — кошелёк (источник: ofac_sdn)",
    "Правило: Высокая частота (+25)",
    "ML: вероятность нетипичного поведения 100% — …"
  ],
  "sources": { "hard_signal": {"active": true}, "rule": {"score": 60.0, "high": true},
               "ml": {"score": 100.0, "high": true}, "graph": {"score": 83.8, "high": true} },
  "scores": {"rule": 60.0, "ml": 100.0, "graph": 83.8, "final": 76.0},
  "summary": {
    "tx_count": 300,
    "total_received": "102112000000000000000",
    "total_sent": "175913956000000000000000",
    "unique_counterparties": 146, "active_period_days": 1581.2,
    "first_seen_at": "2019-...", "last_seen_at": "2024-..."
  },
  "tx_fetched": 300, "truncated": true,
  "collected": true, "cached": false, "elapsed_ms": 2174
}
```

Суммы — **в wei строками**. `truncated: true` означает, что история длиннее
`SCREEN_MAX_TX` и взята только последняя часть.

### Особые случаи

| Ситуация | Ответ |
|---|---|
| Неверный формат адреса | **400**, `detail` с пояснением |
| Адрес без транзакций | **200**, `no_activity: true`, `risk_level: LOW` — не ошибка |
| Лимит / недоступность Etherscan | **503**, `detail` человеческим языком (не 500) |
| Нет токена | **401** |

Метка действует и без транзакций: санкционный адрес даёт **CRITICAL** по Hard
Signal, даже если истории в базе нет.

---

## GET /api/screen/history/ — последние проверки

```json
{"results": [
  {"address": "0x098b…", "risk_level": "CRITICAL", "label": "sanctioned",
   "last_screened_at": "2026-08-06T23:46:12+05:00"}
]}
```

Последние 10 проверенных адресов — для панели «Недавние проверки».

---

## GET /api/graph/ — эго-сеть кошелька («Граф потоков»)

Подграф связей вокруг одного кошелька. **Весь граф (66k узлов) не отдаётся
никогда** — только центр и соседи на ограниченную глубину, с жёстким лимитом.

### Query-параметры

| Параметр | По умолчанию | Описание |
|---|---|---|
| `address` | — | Адрес центрального кошелька (регистр не важен) |
| `wallet_id` | — | ID центра (альтернатива `address`; имеет приоритет) |
| `depth` | `1` | Глубина обхода, максимум **2** (значения выше срезаются) |
| `limit` | `60` | Максимум узлов, максимум **200** |

Нужен ровно один из `address` / `wallet_id`; если кошелёк не найден — **404**.
Мусор в `depth`/`limit` не ломает запрос — берётся значение по умолчанию.

### Пример

```
GET /api/graph/?address=0xd04e9f0945dea8...&depth=1&limit=80
```

```json
{
  "center_id": 21904,
  "center_address": "0xd04e9f0945dea8...",
  "depth": 1,
  "limit": 80,
  "truncated": false,
  "total_neighbors": 1,
  "shown_neighbors": 1,
  "nodes": [
    {
      "id": 21904, "address": "0xd04e9f0945dea8...",
      "label": null, "label_source": null,
      "risk_level": "MEDIUM", "final_score": 0.0, "graph_score": 75.88,
      "tx_count": 3, "is_center": true, "depth": 0
    },
    {
      "id": 5566, "address": "0xd90e2f925da726b5...",
      "label": "mixer", "label_source": "public_known",
      "risk_level": "MEDIUM", "final_score": 0.0, "graph_score": 16.03,
      "tx_count": 94, "is_center": false, "depth": 1
    }
  ],
  "edges": [
    {"source": 21904, "target": 5566, "tx_count": 1, "total_amount": "100000000000000000"}
  ]
}
```

Рёбра направленные (`source` → `target`), `total_amount` — сумма потока **в wei
строкой**. Возвращаются все связи *внутри* набора узлов, а не только с центром, —
поэтому видны и связи соседей между собой.

### Усечение

Соседи ранжируются по объёму потока. Если их больше `limit`, отдаются самые
крупные, а в ответе стоит `truncated: true` вместе с `total_neighbors` и
`shown_neighbors` — интерфейс показывает «показаны N из M связей». Пример: узел с
10 368 связями при `limit=60` отвечает за ~100 мс и возвращает 60 узлов.

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
