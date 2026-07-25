-- Миграция 005: граф-признаки кошелька (Graph Analysis) — четвёртый источник риска.
-- Одна строка на кошелёк. Метрики — из положения узла в сети переводов (NetworkX).
-- graph_score (0..100) и объяснение хранятся здесь; в wallet_risk.graph_score
-- значение подмешивается при расчёте риска (Decision Engine). Идемпотентна.

CREATE TABLE IF NOT EXISTS wallet_graph_features (
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

CREATE INDEX IF NOT EXISTS idx_wallet_graph_score ON wallet_graph_features (graph_score DESC);

COMMENT ON TABLE  wallet_graph_features IS 'Граф-признаки кошелька (положение в сети переводов)';
COMMENT ON COLUMN wallet_graph_features.risky_neighbors IS 'Число прямых соседей, помеченных как миксер/санкции/мошенник';
