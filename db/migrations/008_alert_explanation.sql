-- Миграция 008: кэш LLM-объяснений алертов.
--
-- LLM не участвует в принятии решения — она переформулирует ГОТОВОЕ решение
-- Decision Engine человеческим языком. Генерация стоит денег и времени, поэтому
-- результат кэшируется на связку (алерт, язык, версия решения).
--
-- decision_hash — отпечаток решения (уровень, confidence, причины, вклад
-- источников). Если решение по алерту изменилось, хеш меняется, старая строка
-- считается устаревшей и текст генерируется заново. Идемпотентна.

CREATE TABLE IF NOT EXISTS alert_explanation (
    id            BIGSERIAL PRIMARY KEY,
    alert_id      BIGINT NOT NULL REFERENCES alert(id) ON DELETE CASCADE,
    lang          VARCHAR(5)  NOT NULL,          -- ru / kk / en
    decision_hash VARCHAR(64) NOT NULL,          -- sha256 решения на момент генерации

    text          TEXT        NOT NULL,          -- сгенерированное объяснение
    model         VARCHAR(60) NOT NULL,          -- какая модель сгенерировала
    generated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT uq_alert_explanation UNIQUE (alert_id, lang, decision_hash)
);

CREATE INDEX IF NOT EXISTS idx_alert_explanation_alert ON alert_explanation (alert_id);

COMMENT ON TABLE  alert_explanation IS 'Кэш LLM-объяснений алертов (не влияет на уровень риска)';
COMMENT ON COLUMN alert_explanation.decision_hash IS 'Отпечаток решения Decision Engine: смена -> объяснение устарело';
