"""ML-поиск аномалий кошельков (Isolation Forest).

Обучение на признаках wallet_features -> оценка аномальности -> ml_score (0–100).
Модель + scaler + метаданные сохраняются в models/anomaly.joblib (joblib).
Объяснимость: топ-3 признака, сильнее всего отклоняющихся от нормы (z-score).
"""
from __future__ import annotations

import logging
import math
from datetime import datetime, timezone
from pathlib import Path

import joblib
import numpy as np
from sklearn.ensemble import IsolationForest
from sklearn.preprocessing import StandardScaler

log = logging.getLogger(__name__)

MODEL_PATH = Path(__file__).resolve().parent.parent / "models" / "anomaly.joblib"

# Порядок признаков фиксирован (совпадает с колонками wallet_features).
FEATURE_COLUMNS = [
    "tx_total", "tx_in", "tx_out",
    "total_received", "total_sent", "avg_amount", "max_amount",
    "in_out_count_ratio", "in_out_value_ratio",
    "unique_counterparties", "unique_senders", "unique_receivers",
    "counterparty_spread",
    "active_period_days", "avg_tx_per_day", "max_tx_24h",
    "small_tx_ratio", "zero_tx_ratio", "transit_ratio",
]

# Тяжелохвостые признаки -> логарифмический масштаб (в т.ч. суммы wei).
LOG_COLS = {
    "tx_total", "tx_in", "tx_out",
    "total_received", "total_sent", "avg_amount", "max_amount",
    "in_out_count_ratio", "in_out_value_ratio",
    "unique_counterparties", "unique_senders", "unique_receivers",
    "active_period_days", "avg_tx_per_day", "max_tx_24h",
}
WEI_COLS = {"total_received", "total_sent", "avg_amount", "max_amount"}

# Человекочитаемые имена для объяснения.
LABELS = {
    "tx_total": "число транзакций", "tx_in": "входящих", "tx_out": "исходящих",
    "total_received": "получено", "total_sent": "отправлено",
    "avg_amount": "средняя сумма", "max_amount": "макс. сумма",
    "in_out_count_ratio": "вход/выход (кол-во)", "in_out_value_ratio": "вход/выход (сумма)",
    "unique_counterparties": "уникальных контрагентов", "unique_senders": "уник. отправителей",
    "unique_receivers": "уник. получателей", "counterparty_spread": "разброс контрагентов",
    "active_period_days": "активный период (дни)", "avg_tx_per_day": "транзакций/день",
    "max_tx_24h": "макс. за 24ч", "small_tx_ratio": "доля мелких",
    "zero_tx_ratio": "доля нулевых", "transit_ratio": "транзитность",
}


def _row_to_vector(feats: dict) -> list[float]:
    """dict признаков -> числовой вектор (с лог-масштабом для тяжёлых признаков)."""
    vec = []
    for col in FEATURE_COLUMNS:
        v = float(feats[col])
        if col in LOG_COLS:
            v = math.log1p(max(v, 0.0))
        vec.append(v)
    return vec


def _fmt_value(col: str, raw) -> str:
    v = float(raw)
    if col in WEI_COLS:
        return f"{v / 1e18:.3g} ETH"
    if v == int(v):
        return str(int(v))
    return f"{v:.3g}"


class AnomalyModel:
    """Обёртка над IsolationForest + StandardScaler + нормализация в 0–100."""

    def __init__(self, model, scaler, score_lo, score_hi, meta):
        self.model = model
        self.scaler = scaler
        self.score_lo = score_lo   # перцентили decision_function на обучении
        self.score_hi = score_hi
        self.meta = meta

    # ---- Сохранение / загрузка ----
    def save(self, path: Path = MODEL_PATH) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump(
            {"model": self.model, "scaler": self.scaler,
             "score_lo": self.score_lo, "score_hi": self.score_hi,
             "columns": FEATURE_COLUMNS, "meta": self.meta},
            path,
        )

    @staticmethod
    def load(path: Path = MODEL_PATH) -> "AnomalyModel | None":
        if not path.exists():
            return None
        d = joblib.load(path)
        return AnomalyModel(d["model"], d["scaler"], d["score_lo"], d["score_hi"], d["meta"])

    # ---- Применение ----
    def score_one(self, feats: dict) -> tuple[int, str]:
        """Признаки кошелька -> (ml_score 0–100, объяснение)."""
        xs = self.scaler.transform([_row_to_vector(feats)])[0]
        d = float(self.model.decision_function([xs])[0])
        span = self.score_hi - self.score_lo
        ml = 100.0 * (self.score_hi - d) / span if span > 0 else 0.0
        ml = max(0.0, min(100.0, ml))
        return round(ml), self._explain(xs, feats)

    def _explain(self, xs, feats: dict) -> str:
        """Топ-3 признака с наибольшим |z| (сильнее всего отклоняются от нормы)."""
        order = sorted(range(len(xs)), key=lambda i: abs(xs[i]), reverse=True)[:3]
        parts = []
        for i in order:
            col = FEATURE_COLUMNS[i]
            direction = "аномально высокий" if xs[i] > 0 else "аномально низкий"
            parts.append(f"{LABELS.get(col, col)}={_fmt_value(col, feats[col])} ({direction})")
        return "; ".join(parts)


def train(feature_rows: list[dict], contamination: float = 0.06,
          n_estimators: int = 200, random_state: int = 42) -> tuple[AnomalyModel, np.ndarray]:
    """Обучить модель на списке dict-признаков (вырожденные строки отсеивает вызывающий).
    Возвращает (модель, ml_scores обучения) — ml_scores выровнены с feature_rows."""
    X = np.array([_row_to_vector(r) for r in feature_rows], dtype=float)

    scaler = StandardScaler().fit(X)
    Xs = scaler.transform(X)

    model = IsolationForest(
        n_estimators=n_estimators, contamination=contamination,
        random_state=random_state, n_jobs=-1,
    ).fit(Xs)

    d = model.decision_function(Xs)
    score_lo, score_hi = float(np.percentile(d, 1)), float(np.percentile(d, 99))
    span = score_hi - score_lo or 1.0
    ml_scores = np.clip(100.0 * (score_hi - d) / span, 0, 100)

    meta = {
        "trained_at": datetime.now(timezone.utc).isoformat(),
        "n_samples": len(feature_rows), "contamination": contamination,
        "n_estimators": n_estimators,
    }
    return AnomalyModel(model, scaler, score_lo, score_hi, meta), ml_scores
