-- Миграция 006: кэш скрининга адресов по запросу (POST /api/screen/).
-- Хранит последний результат проверки, чтобы не дёргать Etherscan повторно
-- в течение SCREEN_CACHE_MINUTES. Одна строка на адрес. Идемпотентна.

CREATE TABLE IF NOT EXISTS address_screening (
    address          VARCHAR(128) PRIMARY KEY,   -- в нижнем регистре
    network_id       INTEGER NOT NULL REFERENCES blockchain_network(id),
    wallet_id        BIGINT REFERENCES wallet(id) ON DELETE SET NULL,

    result           JSONB NOT NULL,             -- готовый ответ скрининга
    tx_fetched       INTEGER NOT NULL DEFAULT 0, -- сколько транзакций подтянули
    last_screened_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    screen_count     INTEGER NOT NULL DEFAULT 1  -- сколько раз проверяли
);

CREATE INDEX IF NOT EXISTS idx_screening_last ON address_screening (last_screened_at DESC);

COMMENT ON TABLE address_screening IS 'Кэш и история скрининга адресов по запросу';
