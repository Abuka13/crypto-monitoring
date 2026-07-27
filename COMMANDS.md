# Шпаргалка команд

Все команды запускаются из корня проекта
(`c:\Users\UserHome\Documents\GitHub\crypto-monitoring`).

## 0. Один раз за сессию PowerShell — UTF-8

Иначе Windows-консоль коверкает кириллицу в выводе:

```powershell
$env:PYTHONUTF8 = "1"; $env:PYTHONIOENCODING = "utf-8"
```

## 1. Подготовка (один раз)

```powershell
# установить зависимости
python -m pip install -r requirements.txt

# проверить, что конфиг и подключение к БД в порядке (секреты не печатаются)
python -c "from collector.config import Config; c=Config.load(); print('config OK, DB set:', bool(c.database_url), 'key set:', bool(c.etherscan_api_key))"
python -c "from collector import db; from collector.config import Config; c=Config.load(); conn=db.connect(c.database_url); print('Ethereum network_id =', db.get_network_id(conn,'Ethereum'))"
```

> Конфигурация берётся из `.env` (шаблон — `.env.example`). Файл `.env` в git не попадает.

## 2. Сбор данных из Ethereum

```powershell
# справка по всем флагам
python -m collector --help

# собрать транзакции адреса (--max бережёт бесплатный ключ Etherscan)
python -m collector --address 0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045 --max 15 -v

# повтор той же команды НЕ задваивает данные (идемпотентность)
python -m collector --address 0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045 --max 15

# собрать все транзакции одного блока
python -m collector --block 19000000 -v
```

## 2a. Слежение за новыми блоками (свежие транзакции)

Постоянно опрашивает вершину цепочки и подтягивает новые блоки. Останавливается
по Ctrl+C. Курсор последнего блока сохраняется в `.collector_state.json`, поэтому
после перезапуска слежение продолжается с того же места.

```powershell
# следить с текущей вершины (только сбор)
python -m collector --follow -v

# ПОЛНЫЙ конвейер реального времени: блок -> сбор -> расчёт риска -> алерты
python -m collector --follow --score -v

# реже опрашивать и брать больше блоков за цикл (если отстаём)
python -m collector --follow --score --poll-interval 20 --max-blocks-per-cycle 5 -v

# начать с конкретного блока (догон истории)
python -m collector --follow --score --from-block 25431470 -v
```

С флагом `--score` после ингеста каждого блока риск считается **инкрементально** —
только по транзакциям и кошелькам этого блока, без пересчёта всей базы (доли секунды
на блок). Без `--score` — только сбор; отдельная команда `--score-risk` (пересчёт всей
базы) тоже работает как раньше.

> Внимание: `--follow` тянет ПОЛНЫЕ блоки Ethereum (сотни транзакций каждый), база
> растёт быстро. В режиме блока комиссия `gas_fee` не считается (нужны receipts) —
> для риск-движка это не важно.

**Чтобы слежение работало стабильно/в фоне** (на выбор):
- просто оставить окно терминала открытым (самое простое для показа);
- Планировщик задач Windows: задача «при входе в систему» запускает команду выше;
- держать в фоне средствами ОС (NSSM/служба) — для постоянной работы на сервере.

## 3. Расчёт риска и генерация алертов (Rule Engine)

```powershell
# применить метки адресов (миксеры/биржи/санкции) из data/labels_seed.json
python -m collector --seed-labels

# посчитать риск по уже собранным данным + показать примеры алертов
python -m collector --score-risk -v

# числовые признаки кошельков для ML (порог по числу транзакций настраивается)
python -m collector --compute-features
python -m collector --compute-features --min-tx 10

# ML-аномалии (Isolation Forest): обучить -> применить (гибридный риск)
python -m collector --train-anomaly                    # обучить + сохранить в models/
python -m collector --train-anomaly --contamination 0.1  # доля аномалий выше
python -m collector --score-anomaly                    # ml_score + пересчёт риска кошельков

# Граф-анализ сети переводов (NetworkX): построить -> применить
python -m collector --build-graph                      # граф-метрики -> wallet_graph_features
python -m collector --score-graph                      # graph_score + пересчёт риска кошельков
```

Порядок ML-этапа: `--compute-features` → `--train-anomaly` → `--score-anomaly`.
После обучения модель автоматически подмешивается в `--score-risk` и `--follow --score`.

Порядок граф-этапа: `--seed-labels` (метки нужны для метрики «связь с рисковыми
узлами») → `--build-graph` → `--score-graph`. Обе команды идемпотентны. После
`--build-graph` граф автоматически подмешивается и в `--score-risk`, и в
`--follow --score`; если граф не посчитан — система работает как раньше.

`--build-graph` печатает топ-10 кошельков по `graph_score` с объяснением и
sanity-check по биржам (высокий граф-скор у биржи — норма, но алерта быть не должно:
срабатывает подавление доверенных сущностей `DECISION_TRUSTED_LABELS`).

## 4. Очистка данных (сохраняет справочники)

Удаляет `wallet`, `tx`, `transaction_risk`, `wallet_risk`, `alert`.
НЕ трогает `blockchain_network` и `rule`.

```powershell
# ПРЕДПРОСМОТР — показывает, что удалится, ничего не трогает
python -m collector --reset-data

# РЕАЛЬНОЕ удаление — только с флагом --yes
python -m collector --reset-data --yes
```

## 5. Чистый прогон с нуля

```powershell
$env:PYTHONUTF8 = "1"; $env:PYTHONIOENCODING = "utf-8"
python -m collector --reset-data --yes
python -m collector --address 0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045 --max 15 -v
python -m collector --score-risk -v
```

## 6. Проверка, что легло в БД (без psql)

```powershell
# счётчики по всем таблицам
python -c "from collector import db; from collector.config import Config; c=Config.load(); conn=db.connect(c.database_url); cur=conn.cursor(); [print(t, '=', (cur.execute(f'SELECT count(*) FROM {t}'), cur.fetchone()[0])[1]) for t in ('wallet','tx','transaction_risk','wallet_risk','alert')]"

# открытые алерты с причиной (выборка аналитика)
python -c "from collector import db; from collector.config import Config; c=Config.load(); conn=db.connect(c.database_url); [print(f'[{l}] {st} | {ti} :: {d}') for tt,l,st,ti,d,ca in db.get_sample_alerts(conn, 10)]"
```

## 7. Проверка через SQL (pgAdmin / DBeaver)

```sql
-- сколько чего собрано/посчитано
SELECT 'wallet' t, count(*) FROM wallet
UNION ALL SELECT 'tx', count(*) FROM tx
UNION ALL SELECT 'transaction_risk', count(*) FROM transaction_risk
UNION ALL SELECT 'wallet_risk', count(*) FROM wallet_risk
UNION ALL SELECT 'alert', count(*) FROM alert;

-- суммы в wei хранятся точно (без float-округления)
SELECT tx_hash, amount, block_number, transaction_timestamp, status
FROM tx ORDER BY transaction_timestamp DESC LIMIT 10;

-- распределение оценок транзакций по уровням риска
SELECT risk_level, count(*), min(final_score), max(final_score)
FROM transaction_risk GROUP BY risk_level ORDER BY 2 DESC;

-- алерты: уровень, причина, ссылка ровно на один источник риска
SELECT target_type, level, status, title, description,
       transaction_risk_id, wallet_risk_id
FROM alert ORDER BY id DESC LIMIT 10;

-- главная выборка аналитика: открытые алерты, свежие сверху
SELECT id, level, title, created_at FROM alert
WHERE status = 'open' ORDER BY created_at DESC;

-- активные правила (включая демо-правило)
SELECT id, name, score, is_active FROM rule ORDER BY id;
```

## 8. Настройка чувствительности правил

Добавь в `.env` и перезапусти `--score-risk` — изменится число сработавших правил и алертов:

```dotenv
RISK_LARGE_AMOUNT_WEI=10000000000000000000      # «Большая сумма», порог (10 ETH)
RISK_NEW_WALLET_MAX_AGE_DAYS=30                 # «Новый кошелёк»: не старше N дней
RISK_HIGH_FREQ_COUNT=50                         # «Высокая частота»: >= N транзакций (mainnet)
RISK_HIGH_FREQ_WINDOW_HOURS=24                  #   в окне M часов
RISK_STRUCTURING_SMALL_WEI=10000000000000000    # «Дробление»: порог «мелкой» суммы (0.01 ETH)
RISK_STRUCTURING_MIN_COUNT=30                   #   и минимум таких операций (mainnet)
```

## 9. Настройка граф-анализа

Веса — это МАКСИМАЛЬНЫЙ вклад фактора по отдельности (агрегация noisy-OR, не среднее),
поэтому их сумма не обязана равняться 1. После правки — перезапусти `--build-graph`:

```dotenv
GRAPH_MIN_TX=3                   # фокус-набор: кошельки с >= N транзакций (или с меткой)
GRAPH_RISKY_LABELS=mixer,sanctioned,fraud,blacklist  # какие соседи считаются рисковыми
GRAPH_CENTRALITY_REF=500         # степень узла, дающая полную центральность (=1.0)
GRAPH_FAN_REF=100                # число связей, дающее полную веерность (=1.0)
GRAPH_W_RISKY=0.75               # связь с рисковыми узлами — самая важная метрика
GRAPH_W_CENTRALITY=0.35          # проходность узла
GRAPH_W_TRANSIT=0.30             # транзитность (deposit-and-forward)
GRAPH_W_FAN=0.20                 # веерность (массовый сбор/распыление)
```

Полезные запросы:

```sql
-- топ по графовому риску с объяснением
SELECT w.address, w.label, g.graph_score, g.risky_neighbors, g.graph_explanation
FROM wallet_graph_features g JOIN wallet w ON w.id = g.wallet_id
ORDER BY g.graph_score DESC LIMIT 10;

-- распределение graph_score
SELECT count(*), min(graph_score), max(graph_score),
       percentile_cont(0.9) WITHIN GROUP (ORDER BY graph_score) AS p90
FROM wallet_graph_features;
```
