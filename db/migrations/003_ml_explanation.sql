-- Миграция 003: объяснение ML-аномалии в оценке риска кошелька.
-- Топ-признаки, из-за которых кошелёк выглядит аномальным. Идемпотентна.

ALTER TABLE wallet_risk ADD COLUMN IF NOT EXISTS ml_explanation TEXT;

COMMENT ON COLUMN wallet_risk.ml_explanation IS 'Краткое объяснение ML-аномалии (топ-признаки)';
