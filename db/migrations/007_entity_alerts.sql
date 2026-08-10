-- Миграция 007: алерты на СУЩНОСТЬ + ПРИЧИНУ вместо алертов на транзакцию.
--
-- Было: одна находка порождала сотни сигналов (300 транзакций с санкционным
-- адресом = 300 CRITICAL). Формально каждый верен, но для аналитика это шум:
-- открытие одно, а сигналов триста.
--
-- Стало: алерт создаётся на связку (кошелёк, набор причин). Повторные события с
-- той же причиной не плодят алерты, а добавляются в ДОКАЗАТЕЛЬСТВА.
--
-- transaction_risk_id / wallet_risk_id сохранены как указатель на ПОСЛЕДНЮЮ
-- сработавшую оценку — существующий CHECK «ровно один источник» не нарушается,
-- а вся доказательная база лежит в alert_evidence. Идемпотентна.

-- Сущность и ключ причины
ALTER TABLE alert ADD COLUMN IF NOT EXISTS wallet_id      BIGINT REFERENCES wallet(id) ON DELETE CASCADE;
ALTER TABLE alert ADD COLUMN IF NOT EXISTS reason_key     TEXT;

-- Сводка доказательной базы (денормализована ради списка алертов без JOIN)
ALTER TABLE alert ADD COLUMN IF NOT EXISTS evidence_count INTEGER NOT NULL DEFAULT 0;
ALTER TABLE alert ADD COLUMN IF NOT EXISTS first_event_at TIMESTAMPTZ;
ALTER TABLE alert ADD COLUMN IF NOT EXISTS last_event_at  TIMESTAMPTZ;
ALTER TABLE alert ADD COLUMN IF NOT EXISTS total_amount   NUMERIC(40, 0) NOT NULL DEFAULT 0;

-- Ключ дедупликации: один активный алерт на (кошелёк, причина).
-- Частичный уникальный индекс — закрытые алерты не мешают завести новый.
CREATE UNIQUE INDEX IF NOT EXISTS uq_alert_active_entity_reason
    ON alert (wallet_id, reason_key)
    WHERE status IN ('open', 'in_progress');

CREATE INDEX IF NOT EXISTS idx_alert_wallet ON alert (wallet_id);


-- Доказательства: какие транзакции подтверждают алерт.
-- Отдельная таблица, а не массив в alert: связь многие-ко-многим по смыслу
-- (одна транзакция может быть доказательством по разным причинам), нужна
-- пагинация по доказательствам и честная ссылочная целостность.
-- Суррогатный id, а не составной PK: составные первичные ключи не поддерживаются
-- Django-моделями (managed=False), и объявление FK как primary_key заставило бы
-- ORM считать, что у алерта ровно одно доказательство.
CREATE TABLE IF NOT EXISTS alert_evidence (
    id             BIGSERIAL PRIMARY KEY,
    alert_id       BIGINT NOT NULL REFERENCES alert(id) ON DELETE CASCADE,
    transaction_id BIGINT NOT NULL REFERENCES tx(id)    ON DELETE CASCADE,
    added_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_alert_evidence UNIQUE (alert_id, transaction_id)
);

CREATE INDEX IF NOT EXISTS idx_alert_evidence_tx ON alert_evidence (transaction_id);

COMMENT ON TABLE  alert_evidence IS 'Транзакции-доказательства алерта (сущность + причина)';
COMMENT ON COLUMN alert.reason_key IS 'Нормализованный набор причин: hard:<метка>|rule:<имя>';
COMMENT ON COLUMN alert.wallet_id  IS 'Сущность, к которой относится алерт (кошелёк)';
