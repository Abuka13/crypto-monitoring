-- Миграция 004: Decision Engine.
-- graph_score — задел под Graph Analysis (пока NULL, логика работает без него).
-- decision — структурированное объяснение решения (уровень, уверенность, причины).
-- Идемпотентна.

ALTER TABLE transaction_risk ADD COLUMN IF NOT EXISTS graph_score NUMERIC(6, 2);
ALTER TABLE transaction_risk ADD COLUMN IF NOT EXISTS decision     JSONB;

ALTER TABLE wallet_risk      ADD COLUMN IF NOT EXISTS graph_score NUMERIC(6, 2);
ALTER TABLE wallet_risk      ADD COLUMN IF NOT EXISTS decision     JSONB;

COMMENT ON COLUMN wallet_risk.graph_score IS 'Оценка Graph Analysis (0..100), NULL — модуль не реализован';
COMMENT ON COLUMN wallet_risk.decision    IS 'Решение Decision Engine: уровень, уверенность, источники, причины';
