"""Признаки кошелька и ML-оценка аномальности.

Признаки — вход модели, поэтому их значения проверяются на подготовленных
данных с заранее посчитанным ответом. ML проверяется на диапазон и на то, что
объяснение читаемо: без этого регрессии в форматировании (сырые wei, «аномально
высокий» для пыли) возвращаются незаметно.
"""
from __future__ import annotations

import math
import re
from datetime import datetime, timedelta, timezone

import pytest

from collector import anomaly
from collector.features import _max_in_window, compute_features

ETH = 10 ** 18
T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)


def rows(*items):
    """(sender_id, receiver_id, amount, timestamp) — как отдаёт БД."""
    return list(items)


# --------------------------------------------------------------------------
# Расчёт признаков на подготовленных данных
# --------------------------------------------------------------------------
def test_features_on_known_data(risk_cfg):
    """Кошелёк 1: получил 3 ETH двумя переводами, отправил 1 ETH одним."""
    me, a, b = 1, 2, 3
    data = rows(
        (a, me, 2 * ETH, T0),
        (b, me, 1 * ETH, T0 + timedelta(hours=1)),
        (me, b, 1 * ETH, T0 + timedelta(days=1)),
    )
    f = compute_features(data, me, risk_cfg)

    assert f["tx_total"] == 3
    assert f["tx_in"] == 2 and f["tx_out"] == 1
    assert f["total_received"] == 3 * ETH
    assert f["total_sent"] == 1 * ETH
    assert f["max_amount"] == 2 * ETH
    assert f["avg_amount"] == (2 * ETH + ETH + ETH) // 3
    assert f["unique_senders"] == 2
    assert f["unique_receivers"] == 1
    assert f["unique_counterparties"] == 2      # b и как отправитель, и как получатель
    assert f["in_out_count_ratio"] == pytest.approx(2.0)
    assert f["active_period_days"] == pytest.approx(1.0)
    # Транзитность: min(in,out)/max(in,out) по объёму = 1/3
    assert f["transit_ratio"] == pytest.approx(1 / 3)


def test_features_none_without_transactions(risk_cfg):
    assert compute_features([], 1, risk_cfg) is None


def test_value_ratio_is_a_ratio_not_raw_wei(risk_cfg):
    """При нулевых отправлениях «отношение» не должно вырождаться в сумму wei.

    Раньше знаменатель был 1 wei, и признак принимал значения ~1e18, что портило
    и объяснения, и лог-шкалу модели.
    """
    data = rows((2, 1, 5 * ETH, T0), (3, 1, 5 * ETH, T0 + timedelta(hours=1)))
    f = compute_features(data, 1, risk_cfg)
    assert f["total_sent"] == 0
    assert f["in_out_value_ratio"] < 1e7, "отношение не должно быть масштаба wei"


def test_small_and_zero_tx_ratios(risk_cfg):
    """Доли мелких и нулевых операций считаются от общего числа."""
    small = risk_cfg.structuring_small_amount_wei
    data = rows(
        (2, 1, 0, T0),                            # нулевая
        (2, 1, small // 2, T0 + timedelta(1)),    # мелкая
        (2, 1, 5 * ETH, T0 + timedelta(2)),       # крупная
        (2, 1, 5 * ETH, T0 + timedelta(3)),
    )
    f = compute_features(data, 1, risk_cfg)
    assert f["zero_tx_ratio"] == pytest.approx(0.25)
    assert f["small_tx_ratio"] == pytest.approx(0.25)


def test_max_tx_in_24h_window():
    """Максимум в скользящем окне: всплеск виден, даже если период длинный."""
    burst = [T0 + timedelta(minutes=i) for i in range(5)]
    spread = [T0 + timedelta(days=10 + i) for i in range(3)]
    assert _max_in_window(burst + spread, timedelta(hours=24)) == 5


def test_self_transfer_not_counted_as_counterparty(risk_cfg):
    data = rows((1, 1, ETH, T0))
    f = compute_features(data, 1, risk_cfg)
    assert f["unique_counterparties"] == 0


# --------------------------------------------------------------------------
# ML-оценка
# --------------------------------------------------------------------------
def _training_set(n: int = 60) -> list[dict]:
    """Синтетическая «норма» + один явный выброс."""
    base = []
    for i in range(n):
        base.append({
            "tx_total": 10 + i % 5, "tx_in": 5, "tx_out": 5,
            "total_received": 5 * ETH, "total_sent": 5 * ETH,
            "avg_amount": ETH, "max_amount": 2 * ETH,
            "in_out_count_ratio": 1.0, "in_out_value_ratio": 1.0,
            "unique_counterparties": 4, "unique_senders": 2, "unique_receivers": 2,
            "counterparty_spread": 0.4, "active_period_days": 30.0,
            "avg_tx_per_day": 0.4, "max_tx_24h": 2,
            "small_tx_ratio": 0.1, "zero_tx_ratio": 0.0, "transit_ratio": 0.5,
        })
    outlier = dict(base[0], tx_total=5000, tx_in=5000, tx_out=0,
                   unique_senders=3000, unique_counterparties=3000,
                   max_tx_24h=4000, transit_ratio=0.0, in_out_count_ratio=5000.0)
    return base + [outlier]


@pytest.fixture(scope="module")
def trained():
    data = _training_set()
    model, scores = anomaly.train(data, contamination=0.05, n_estimators=40)
    return model, data, scores


def test_ml_score_within_0_100(trained):
    _, _, scores = trained
    assert scores.min() >= 0 and scores.max() <= 100


def test_ml_score_one_within_0_100(trained):
    model, data, _ = trained
    for row in (data[0], data[-1]):
        score, _ = model.score_one(row)
        assert 0 <= score <= 100
        assert isinstance(score, int)


def test_outlier_scores_above_normal(trained):
    """Явный выброс должен получить оценку выше типичного кошелька."""
    model, data, _ = trained
    normal, _ = model.score_one(data[0])
    outlier, _ = model.score_one(data[-1])
    assert outlier > normal


def test_explanation_is_human_readable(trained):
    """Никаких сырых чисел масштаба wei и старой формулировки «аномально»."""
    model, data, _ = trained
    _, text = model.score_one(data[-1])
    assert text
    assert "аномально" not in text, "формулировка должна быть «выше/ниже типичного»"
    assert not re.search(r"=\d{13,}", text), "сырое число вместо форматированного"
    assert "типичного" in text


def test_dust_amount_not_called_high():
    """Мелкая сумма не должна описываться как «выше типичного»."""
    assert anomaly._is_misleading("total_sent", 0.05 * ETH, z=3.0) is True
    assert anomaly._is_misleading("total_sent", 50 * ETH, z=3.0) is False


@pytest.mark.parametrize("col,raw,expected_fragment", [
    ("total_received", 2 * ETH, "ETH"),
    ("in_out_value_ratio", 1.67, "×"),
    ("transit_ratio", 0.89, "%"),
    ("tx_total", 42, "42"),
])
def test_value_formatting_by_feature_type(col, raw, expected_fragment):
    assert expected_fragment in anomaly._fmt_value(col, raw)


def test_feature_columns_match_vector_length():
    """Порядок признаков фиксирован — вектор и список колонок обязаны совпадать."""
    row = _training_set(1)[0]
    assert len(anomaly._row_to_vector(row)) == len(anomaly.FEATURE_COLUMNS)


def test_log_scale_applied_to_heavy_tailed():
    """Тяжелохвостые признаки уходят в лог-шкалу (иначе модель видит только суммы)."""
    row = _training_set(1)[0]
    vec = anomaly._row_to_vector(row)
    idx = anomaly.FEATURE_COLUMNS.index("total_received")
    assert vec[idx] == pytest.approx(math.log1p(float(row["total_received"])))
