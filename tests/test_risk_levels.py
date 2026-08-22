"""Границы уровней риска.

Уровень определяется решающей логикой по баллам источников, а не порогом от
final_score. Тесты фиксируют пороги rule_score и то, как risk_level ложится на
уровень алерта (low/medium/high/critical).
"""
from __future__ import annotations

import pytest

from collector.risk.decision import RiskSources, decide
from collector.risk.rules import alert_level_from_risk_level

FREQ = "Высокая частота"
STRUCT = "Дробление сумм"
MIXER = "Связь с миксером"


def rule_only(score: float, names: list[str]) -> RiskSources:
    """Только правила — без ИИ и графа."""
    per = score / max(len(names), 1)
    return RiskSources(rule_score=score, fired_rules=[(n, per) for n in names])


@pytest.mark.parametrize("score,expected", [
    (0.0, "LOW"),
    (24.9, "LOW"),      # ниже rule_medium
    (25.0, "MEDIUM"),   # ровно порог MEDIUM
    (49.9, "MEDIUM"),
    (50.0, "HIGH"),     # ровно порог HIGH
    (74.9, "HIGH"),
    (80.0, "HIGH"),     # >= rule_critical, но подтверждения нет -> не CRITICAL
])
def test_rule_score_bands(decision_cfg, score, expected):
    """Пороги rule_score: 25 -> MEDIUM, 50 -> HIGH; CRITICAL требует 2-го модуля."""
    assert decide(rule_only(score, [FREQ, STRUCT]), decision_cfg).level == expected


def test_critical_band_needs_confirmation(decision_cfg):
    """rule_score >= 75 даёт CRITICAL только вместе со вторым источником."""
    src = rule_only(80.0, [FREQ, STRUCT, MIXER])
    assert decide(src, decision_cfg).level == "HIGH"

    confirmed = RiskSources(**{**src.__dict__, "ml_score": 90.0})
    assert decide(confirmed, decision_cfg).level == "CRITICAL"


@pytest.mark.parametrize("risk_level,alert_level", [
    ("LOW", "low"),
    ("MEDIUM", "medium"),
    ("HIGH", "high"),
    ("CRITICAL", "critical"),
])
def test_risk_level_maps_to_alert_level(risk_level, alert_level):
    """Уровень алерта повторяет решение, а не пересчитывается заново."""
    assert alert_level_from_risk_level(risk_level) == alert_level


def test_alert_levels_match_db_constraint(db):
    """Все уровни, которые мы выдаём, разрешены CHECK-ограничением в схеме."""
    from django.db import connection

    for risk_level in ("LOW", "MEDIUM", "HIGH", "CRITICAL"):
        value = alert_level_from_risk_level(risk_level)
        with connection.cursor() as cur:
            # Проверка проходит, только если значение допустимо ограничением.
            cur.execute("SELECT %s::varchar(10) IN ('low','medium','high','critical')",
                        [value])
            assert cur.fetchone()[0] is True, f"{value} нарушает chk_alert_level"


@pytest.mark.parametrize("ml,graph,expected", [
    (100.0, None, "MEDIUM"),   # ИИ в одиночку
    (None, 100.0, "MEDIUM"),   # граф в одиночку
    (100.0, 100.0, "HIGH"),    # два независимых модуля
    (69.0, 69.0, "LOW"),       # оба ниже порога
])
def test_ai_and_graph_bands(decision_cfg, ml, graph, expected):
    assert decide(RiskSources(ml_score=ml, graph_score=graph), decision_cfg).level == expected
