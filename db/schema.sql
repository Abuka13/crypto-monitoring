-- ============================================================
--  Система мониторинга криптовалютных операций
--  Схема базы данных (PostgreSQL) — первая версия (Ethereum)
-- ============================================================
--  Принцип: сначала платформа мониторинга, затем модуль ИИ.
--  Денежные суммы хранятся в NUMERIC (Ethereum использует wei,
--  1 ETH = 10^18 wei — числа слишком большие для BIGINT, а FLOAT
--  теряет точность, что недопустимо для финансовых данных).
-- ============================================================

    
-- ------------------------------------------------------------
-- 1. BlockchainNetwork — поддерживаемые блокчейн-сети
--    Заведена сразу, хотя активна только Ethereum, чтобы позже
--    добавить Bitcoin / TRON / BNB без переделки модели.
-- ------------------------------------------------------------
CREATE TABLE blockchain_network (
    id          SERIAL PRIMARY KEY,
    name        VARCHAR(50)  NOT NULL UNIQUE,      -- Ethereum, Bitcoin, ...
    symbol      VARCHAR(10)  NOT NULL,             -- ETH, BTC, ...
    is_active   BOOLEAN      NOT NULL DEFAULT TRUE,
    created_at  TIMESTAMPTZ  NOT NULL DEFAULT now()
);


-- ------------------------------------------------------------
-- 2. Wallet — криптокошелёк (адрес)
--    Хранит агрегированную статистику и общий риск-скор.
-- ------------------------------------------------------------
CREATE TABLE wallet (
    id                  BIGSERIAL PRIMARY KEY,
    address             VARCHAR(128) NOT NULL,         -- адрес (Ethereum ~42 симв., запас для др. сетей)
    network_id          INTEGER      NOT NULL REFERENCES blockchain_network(id),

    first_seen_at       TIMESTAMPTZ,
    last_seen_at        TIMESTAMPTZ,
    transaction_count   INTEGER      NOT NULL DEFAULT 0,
    total_received      NUMERIC(40, 0) NOT NULL DEFAULT 0,  -- в wei
    total_sent          NUMERIC(40, 0) NOT NULL DEFAULT 0,  -- в wei

    risk_score          NUMERIC(6, 2) NOT NULL DEFAULT 0,   -- агрегированный риск 0..100
    is_flagged          BOOLEAN      NOT NULL DEFAULT FALSE,
    label               VARCHAR(50),                        -- mixer / exchange / sanctioned / fraud / NULL
    label_source        VARCHAR(50),                        -- ofac_sdn / public_known / etherscan_tag / manual
    labeled_at          TIMESTAMPTZ,                        -- когда проставлена метка

    created_at          TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ  NOT NULL DEFAULT now(),

    -- один и тот же адрес уникален в пределах сети
    CONSTRAINT uq_wallet_address_network UNIQUE (network_id, address)
);

-- Быстрый поиск кошелька по адресу
CREATE INDEX idx_wallet_address    ON wallet (address);
-- Быстрая выборка подозрительных кошельков для аналитика
CREATE INDEX idx_wallet_flagged    ON wallet (is_flagged) WHERE is_flagged = TRUE;
CREATE INDEX idx_wallet_risk_score ON wallet (risk_score DESC);


-- ------------------------------------------------------------
-- 3. Transaction — отдельная операция в блокчейне
--    "transaction" — зарезервированное слово в SQL, поэтому
--    таблица называется tx (без кавычек, безопасно).
-- ------------------------------------------------------------
CREATE TABLE tx (
    id                      BIGSERIAL PRIMARY KEY,
    tx_hash                 VARCHAR(80) NOT NULL,          -- хеш (Ethereum 66 симв.)
    network_id              INTEGER     NOT NULL REFERENCES blockchain_network(id),

    sender_wallet_id        BIGINT      NOT NULL REFERENCES wallet(id),
    receiver_wallet_id      BIGINT      NOT NULL REFERENCES wallet(id),

    amount                  NUMERIC(40, 0) NOT NULL,        -- в wei
    currency                VARCHAR(10) NOT NULL DEFAULT 'ETH',
    gas_fee                 NUMERIC(40, 0) NOT NULL DEFAULT 0,
    block_number            BIGINT      NOT NULL,
    transaction_timestamp   TIMESTAMPTZ NOT NULL,
    status                  VARCHAR(20) NOT NULL DEFAULT 'success',

    created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),

    -- один хеш уникален в пределах сети (одна и та же транзакция не дублируется)
    CONSTRAINT uq_tx_hash_network UNIQUE (network_id, tx_hash),
    CONSTRAINT chk_tx_status CHECK (status IN ('success', 'failed', 'pending'))
);

-- Индексы под типовые запросы аналитика
CREATE INDEX idx_tx_hash      ON tx (tx_hash);
CREATE INDEX idx_tx_sender    ON tx (sender_wallet_id);
CREATE INDEX idx_tx_receiver  ON tx (receiver_wallet_id);
CREATE INDEX idx_tx_timestamp ON tx (transaction_timestamp DESC);
CREATE INDEX idx_tx_block     ON tx (block_number);


-- ------------------------------------------------------------
-- 4. Rule — правило расчёта риска (для Rule Engine)
--    Вынесено в таблицу, чтобы менять правила без правки кода.
-- ------------------------------------------------------------
CREATE TABLE rule (
    id          SERIAL PRIMARY KEY,
    name        VARCHAR(100) NOT NULL UNIQUE,
    description TEXT,
    score       NUMERIC(6, 2) NOT NULL,             -- вклад правила в риск
    is_active   BOOLEAN      NOT NULL DEFAULT TRUE,
    created_at  TIMESTAMPTZ  NOT NULL DEFAULT now()
);


-- ------------------------------------------------------------
-- 5. TransactionRisk — оценка риска отдельной транзакции
--    История: каждый пересчёт = новая строка.
--    rule_score и ml_score хранятся раздельно (Rule Engine и
--    AI Engine пишут свой вклад независимо).
-- ------------------------------------------------------------
CREATE TABLE transaction_risk (
    id              BIGSERIAL PRIMARY KEY,
    transaction_id  BIGINT       NOT NULL REFERENCES tx(id) ON DELETE CASCADE,

    rule_score      NUMERIC(6, 2) NOT NULL DEFAULT 0,
    ml_score        NUMERIC(6, 2) NOT NULL DEFAULT 0,
    graph_score     NUMERIC(6, 2),                       -- Graph Analysis (пока NULL)
    final_score     NUMERIC(6, 2) NOT NULL DEFAULT 0,    -- справочное (совместимость)
    risk_level      VARCHAR(10)  NOT NULL,               -- решение Decision Engine
    decision        JSONB,                               -- объяснение решения

    created_at      TIMESTAMPTZ  NOT NULL DEFAULT now(),

    CONSTRAINT chk_txrisk_level CHECK (risk_level IN ('LOW', 'MEDIUM', 'HIGH', 'CRITICAL'))
);

-- Быстро достать последнюю оценку для транзакции
CREATE INDEX idx_txrisk_transaction ON transaction_risk (transaction_id, created_at DESC);


-- ------------------------------------------------------------
-- 6. WalletRisk — оценка риска кошелька в целом
--    Нужна потому, что кошелёк может быть подозрительным, даже
--    если каждая отдельная транзакция невинна.
-- ------------------------------------------------------------
CREATE TABLE wallet_risk (
    id          BIGSERIAL PRIMARY KEY,
    wallet_id   BIGINT       NOT NULL REFERENCES wallet(id) ON DELETE CASCADE,

    rule_score  NUMERIC(6, 2) NOT NULL DEFAULT 0,
    ml_score    NUMERIC(6, 2) NOT NULL DEFAULT 0,
    graph_score NUMERIC(6, 2),                           -- Graph Analysis (пока NULL)
    final_score NUMERIC(6, 2) NOT NULL DEFAULT 0,        -- справочное (совместимость)
    risk_level  VARCHAR(10)  NOT NULL,                   -- решение Decision Engine
    ml_explanation TEXT,                                 -- топ-признаки ML-аномалии
    decision    JSONB,                                   -- объяснение решения

    created_at  TIMESTAMPTZ  NOT NULL DEFAULT now(),

    CONSTRAINT chk_walletrisk_level CHECK (risk_level IN ('LOW', 'MEDIUM', 'HIGH', 'CRITICAL'))
);

CREATE INDEX idx_walletrisk_wallet ON wallet_risk (wallet_id, created_at DESC);


-- ------------------------------------------------------------
-- 8. WalletFeatures — числовые признаки поведения кошелька
--    Одна строка на кошелёк, вход для ML (Isolation Forest).
--    Считаются командой --compute-features; wei-суммы в NUMERIC.
-- ------------------------------------------------------------
CREATE TABLE wallet_features (
    wallet_id             BIGINT PRIMARY KEY REFERENCES wallet(id) ON DELETE CASCADE,

    tx_total              INTEGER NOT NULL,        -- всего транзакций
    tx_in                 INTEGER NOT NULL,        -- входящих
    tx_out                INTEGER NOT NULL,        -- исходящих

    total_received        NUMERIC(40, 0) NOT NULL, -- wei
    total_sent            NUMERIC(40, 0) NOT NULL, -- wei
    avg_amount            NUMERIC(40, 0) NOT NULL, -- средняя сумма транзакции, wei
    max_amount            NUMERIC(40, 0) NOT NULL, -- максимальная сумма, wei

    in_out_count_ratio    DOUBLE PRECISION NOT NULL, -- tx_in / max(tx_out,1)
    in_out_value_ratio    DOUBLE PRECISION NOT NULL, -- received / max(sent,1)

    unique_counterparties INTEGER NOT NULL,        -- разных контрагентов
    unique_senders        INTEGER NOT NULL,        -- разных отправителей (входящие)
    unique_receivers      INTEGER NOT NULL,        -- разных получателей (исходящие)
    counterparty_spread   DOUBLE PRECISION NOT NULL, -- unique_counterparties / tx_total

    active_period_days    DOUBLE PRECISION NOT NULL, -- от первой до последней tx, дни
    avg_tx_per_day        DOUBLE PRECISION NOT NULL, -- средняя частота
    max_tx_24h            INTEGER NOT NULL,          -- макс. транзакций за 24ч

    small_tx_ratio        DOUBLE PRECISION NOT NULL, -- доля мелких операций (structuring)
    zero_tx_ratio         DOUBLE PRECISION NOT NULL, -- доля нулевых (вызовы контрактов)
    transit_ratio         DOUBLE PRECISION NOT NULL, -- транзитность: min(in,out)/max(in,out) по сумме

    computed_at           TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_wallet_features_txtotal ON wallet_features (tx_total DESC);


-- ------------------------------------------------------------
-- 9. WalletGraphFeatures — граф-признаки кошелька (Graph Analysis)
--    Одна строка на кошелёк. Оценивает риск по ПОЛОЖЕНИЮ узла в сети
--    переводов (in/out-степень, центральность, связь с рисковыми узлами,
--    транзитность, веерность). Заполняется командой --build-graph; итоговый
--    graph_score подмешивается в wallet_risk через Decision Engine.
-- ------------------------------------------------------------
CREATE TABLE wallet_graph_features (
    wallet_id            BIGINT PRIMARY KEY REFERENCES wallet(id) ON DELETE CASCADE,

    in_degree            INTEGER NOT NULL,          -- уникальных входящих связей (отправителей)
    out_degree           INTEGER NOT NULL,          -- уникальных исходящих связей (получателей)
    degree_centrality    DOUBLE PRECISION NOT NULL, -- «проходность» узла (нормированная степень)

    risky_neighbors      INTEGER NOT NULL,          -- соседей с меткой mixer/sanctioned/fraud
    risky_neighbor_ratio DOUBLE PRECISION NOT NULL, -- доля рисковых среди всех соседей

    transit_ratio        DOUBLE PRECISION NOT NULL, -- транзитность: min(in,out)/max(in,out) по потоку
    fan_in_ratio         DOUBLE PRECISION NOT NULL, -- веерность сбора (много входящих связей)
    fan_out_ratio        DOUBLE PRECISION NOT NULL, -- веерность распыления (много исходящих связей)

    graph_score          NUMERIC(6, 2) NOT NULL,    -- итоговый графовый риск 0..100
    graph_explanation    TEXT,                      -- какие метрики подняли оценку

    computed_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_wallet_graph_score ON wallet_graph_features (graph_score DESC);


-- ------------------------------------------------------------
-- 7. Alert — оповещение для аналитика
--    Ссылается ЛИБО на transaction_risk, ЛИБО на wallet_risk.
--    CHECK гарантирует, что заполнен ровно один из двух FK —
--    база сама не даст создать "висячий" или двойной алерт.
-- ------------------------------------------------------------
CREATE TABLE alert (
    id                  BIGSERIAL PRIMARY KEY,

    transaction_risk_id BIGINT REFERENCES transaction_risk(id) ON DELETE CASCADE,
    wallet_risk_id      BIGINT REFERENCES wallet_risk(id)      ON DELETE CASCADE,
    target_type         VARCHAR(15) NOT NULL,                  -- 'transaction' / 'wallet'

    title               VARCHAR(200) NOT NULL,
    description         TEXT,
    level               VARCHAR(10)  NOT NULL,
    status              VARCHAR(20)  NOT NULL DEFAULT 'open',

    created_at          TIMESTAMPTZ  NOT NULL DEFAULT now(),
    resolved_at         TIMESTAMPTZ,

    CONSTRAINT chk_alert_target_type CHECK (target_type IN ('transaction', 'wallet')),
    CONSTRAINT chk_alert_level  CHECK (level  IN ('low', 'medium', 'high', 'critical')),
    CONSTRAINT chk_alert_status CHECK (status IN ('open', 'in_progress', 'closed', 'false_positive')),

    -- ровно один из двух источников риска должен быть заполнен
    CONSTRAINT chk_alert_one_source CHECK (
        (transaction_risk_id IS NOT NULL AND wallet_risk_id IS NULL)
        OR
        (transaction_risk_id IS NULL AND wallet_risk_id IS NOT NULL)
    )
);

-- Главная выборка аналитика: открытые алерты, свежие сверху
CREATE INDEX idx_alert_status ON alert (status, created_at DESC);
CREATE INDEX idx_alert_level  ON alert (level);


-- ============================================================
--  Стартовые данные
-- ============================================================
INSERT INTO blockchain_network (name, symbol, is_active) VALUES
    ('Ethereum', 'ETH', TRUE),
    ('Bitcoin',  'BTC', FALSE),   -- задел на будущее
    ('TRON',     'TRX', FALSE),
    ('BNB Chain','BNB', FALSE);

-- Примеры правил для Rule Engine
INSERT INTO rule (name, description, score, is_active) VALUES
    ('Большая сумма',         'Сумма транзакции превышает заданный порог',                 30.00, TRUE),
    ('Новый кошелёк',         'Кошелёк создан недавно и сразу проводит крупные операции',  20.00, TRUE),
    ('Высокая частота',       'Большое число операций за короткий промежуток времени',     25.00, TRUE),
    ('Связь с миксером',      'Один из участников помечен как миксер',                      40.00, TRUE),
    ('Дробление сумм',        'Множество мелких операций (возможный structuring)',          35.00, TRUE),
    ('Санкционный адрес',     'Отправитель или получатель в санкционном списке (OFAC SDN)', 50.00, TRUE);
