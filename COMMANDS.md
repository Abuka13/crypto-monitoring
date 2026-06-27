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

## 3. Расчёт риска и генерация алертов (Rule Engine)

```powershell
# посчитать риск по уже собранным данным + показать примеры алертов
python -m collector --score-risk -v
```

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
RISK_LARGE_AMOUNT_WEI=10000000000000000000      # «Большая сумма», боевой порог (10 ETH)
RISK_LARGE_AMOUNT_TEST_WEI=100000000000000      # «Большая сумма (тест)», демо-порог (0.0001 ETH)
RISK_NEW_WALLET_MAX_AGE_DAYS=30                 # «Новый кошелёк»: не старше N дней
RISK_HIGH_FREQ_COUNT=10                         # «Высокая частота»: >= N транзакций
RISK_HIGH_FREQ_WINDOW_HOURS=24                  #   в окне M часов
RISK_STRUCTURING_SMALL_WEI=10000000000000000    # «Дробление»: порог «мелкой» суммы (0.01 ETH)
RISK_STRUCTURING_MIN_COUNT=10                   #   и минимум таких операций
```
