-- Миграция 002: числовые признаки кошельков для ML (Isolation Forest).
-- Одна строка на кошелёк. wei-суммы — NUMERIC (без float). Идемпотентна.

CREATE TABLE IF NOT EXISTS wallet_features (
    wallet_id             BIGINT PRIMARY KEY REFERENCES wallet(id) ON DELETE CASCADE,

    -- Объём активности
    tx_total              INTEGER NOT NULL,        -- всего транзакций
    tx_in                 INTEGER NOT NULL,        -- входящих (кошелёк — получатель)
    tx_out                INTEGER NOT NULL,        -- исходящих (кошелёк — отправитель)

    -- Суммы (wei)
    total_received        NUMERIC(40, 0) NOT NULL,
    total_sent            NUMERIC(40, 0) NOT NULL,
    avg_amount            NUMERIC(40, 0) NOT NULL, -- средняя сумма транзакции
    max_amount            NUMERIC(40, 0) NOT NULL, -- максимальная сумма

    -- Соотношения вход/выход
    in_out_count_ratio    DOUBLE PRECISION NOT NULL, -- tx_in / max(tx_out,1)
    in_out_value_ratio    DOUBLE PRECISION NOT NULL, -- received / max(sent,1)

    -- Контрагенты
    unique_counterparties INTEGER NOT NULL,        -- разных адресов-контрагентов
    unique_senders        INTEGER NOT NULL,        -- разных отправителей (по входящим)
    unique_receivers      INTEGER NOT NULL,        -- разных получателей (по исходящим)
    counterparty_spread   DOUBLE PRECISION NOT NULL, -- unique_counterparties / tx_total

    -- Время
    active_period_days    DOUBLE PRECISION NOT NULL, -- от первой до последней tx, дни
    avg_tx_per_day        DOUBLE PRECISION NOT NULL, -- средняя частота
    max_tx_24h            INTEGER NOT NULL,          -- макс. транзакций за 24ч

    -- Паттерны
    small_tx_ratio        DOUBLE PRECISION NOT NULL, -- доля мелких операций (structuring)
    zero_tx_ratio         DOUBLE PRECISION NOT NULL, -- доля нулевых (вызовы контрактов)
    transit_ratio         DOUBLE PRECISION NOT NULL, -- транзитность: min(in,out)/max(in,out) по сумме

    computed_at           TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_wallet_features_txtotal ON wallet_features (tx_total DESC);
