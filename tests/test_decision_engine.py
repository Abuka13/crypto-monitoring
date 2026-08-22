"""Инварианты Decision Engine — самая важная часть системы.

Уровень риска определяет решающая логика над независимыми источниками, а не
формула. Эти тесты фиксируют её гарантии: без них любая правка порогов или
весов может незаметно превратить ИИ из подтверждающего сигнала в решающий.

Чистая логика — базы данных здесь нет.
"""
from __future__ import annotations

import pytest

from collector.risk.decision import RiskSources, decide

MIXER = "Связь с миксером"
SANCTION = ("sanctioned", "ofac_sdn", "кошелёк")


def level(sources: RiskSources, cfg) -> str:
    return decide(sources, cfg).level


# --------------------------------------------------------------------------
# Hard Signal — наивысший приоритет
# --------------------------------------------------------------------------
def test_hard_signal_gives_critical(decision_cfg):
    """Санкционная метка -> CRITICAL даже при нулевых остальных источниках."""
    d = decide(RiskSources(hard_signals=[SANCTION]), decision_cfg)
    assert d.level == "CRITICAL"
    assert d.confidence == pytest.approx(0.99)


def test_hard_signal_wins_over_everything(decision_cfg):
    """Hard Signal не отменяется ни доверенной меткой, ни низкими баллами."""
    d = decide(RiskSources(hard_signals=[SANCTION], label="exchange"), decision_cfg)
    assert d.level == "CRITICAL"


@pytest.mark.parametrize("label", ["sanctioned", "blacklist", "fraud"])
def test_all_hard_labels_give_critical(decision_cfg, label):
    assert level(RiskSources(hard_signals=[(label, "src", "кошелёк")]), decision_cfg) == "CRITICAL"


# --------------------------------------------------------------------------
# ИИ и граф в одиночку — потолок MEDIUM
# --------------------------------------------------------------------------
def test_ml_alone_capped_at_medium(decision_cfg):
    """Даже ml_score=100 без других сигналов не поднимает выше MEDIUM."""
    assert level(RiskSources(ml_score=100.0), decision_cfg) == "MEDIUM"


def test_graph_alone_capped_at_medium(decision_cfg):
    assert level(RiskSources(graph_score=100.0), decision_cfg) == "MEDIUM"


def test_ml_plus_graph_escalates_to_high(decision_cfg):
    """ML и Graph — РАЗНЫЕ независимые модули: вместе это уже не «в одиночку»."""
    assert level(RiskSources(ml_score=85.0, graph_score=76.0), decision_cfg) == "HIGH"


def test_ml_below_threshold_stays_low(decision_cfg):
    assert level(RiskSources(ml_score=69.0), decision_cfg) == "LOW"


# --------------------------------------------------------------------------
# Правила и подтверждение
# --------------------------------------------------------------------------
def test_strong_rule_alone_is_medium(decision_cfg):
    """Сильное правило само по себе — MEDIUM, не выше."""
    src = RiskSources(rule_score=40.0, fired_rules=[(MIXER, 40.0)])
    assert level(src, decision_cfg) == "MEDIUM"


def test_strong_rule_plus_ml_is_high(decision_cfg):
    src = RiskSources(rule_score=40.0, fired_rules=[(MIXER, 40.0)], ml_score=85.0)
    assert level(src, decision_cfg) == "HIGH"


def test_strong_rule_plus_graph_is_high(decision_cfg):
    src = RiskSources(rule_score=40.0, fired_rules=[(MIXER, 40.0)], graph_score=76.0)
    assert level(src, decision_cfg) == "HIGH"


def test_ai_never_lowers_rule_level(decision_cfg):
    """Уровень от правил — нижняя граница: слабый ИИ его не опускает."""
    strong_rules = RiskSources(
        rule_score=50.0,
        fired_rules=[("Высокая частота", 25.0), ("Дробление сумм", 25.0)],
    )
    without_ai = level(strong_rules, decision_cfg)
    with_weak_ai = level(
        RiskSources(**{**strong_rules.__dict__, "ml_score": 1.0, "graph_score": 0.0}),
        decision_cfg,
    )
    assert without_ai == "HIGH"
    assert with_weak_ai == "HIGH"


# --------------------------------------------------------------------------
# Независимый источник = МОДУЛЬ, а не отдельное правило
# --------------------------------------------------------------------------
def test_many_rules_count_as_one_source(decision_cfg):
    """Три сработавших правила — это ОДИН источник, а не три.

    Иначе CRITICAL срабатывал бы слишком легко: достаточно было бы набрать
    правил внутри одного модуля.
    """
    src = RiskSources(
        rule_score=80.0,
        fired_rules=[("Высокая частота", 25.0), (MIXER, 40.0), ("Дробление сумм", 35.0)],
    )
    d = decide(src, decision_cfg)
    assert d.sources["independent_high_sources"] == ["rule"]
    assert d.level == "HIGH", "без второго модуля CRITICAL давать нельзя"


def test_critical_requires_second_module(decision_cfg):
    """rule_score >= 75 плюс подтверждение вторым модулем -> CRITICAL."""
    fired = [("Высокая частота", 25.0), (MIXER, 40.0), ("Дробление сумм", 35.0)]
    src = RiskSources(rule_score=80.0, fired_rules=fired, graph_score=76.0)
    d = decide(src, decision_cfg)
    assert sorted(d.sources["independent_high_sources"]) == ["graph", "rule"]
    assert d.level == "CRITICAL"


# --------------------------------------------------------------------------
# Доверенные метки (биржи и контракты)
# --------------------------------------------------------------------------
@pytest.mark.parametrize("label", ["exchange", "contract"])
def test_trusted_label_suppresses_ai_only_anomaly(decision_cfg, label):
    """Аномалия ИИ/графа сама по себе не создаёт сигнал по доверенной сущности."""
    d = decide(RiskSources(ml_score=100.0, graph_score=90.0, label=label), decision_cfg)
    assert d.level == "LOW"
    assert d.sources["suppressed_by_trust"] is True
    assert d.confidence == pytest.approx(0.90)


@pytest.mark.parametrize("label", ["exchange", "contract"])
def test_trusted_label_does_not_suppress_rules(decision_cfg, label):
    """Правила по доверенной сущности действуют в полном объёме."""
    src = RiskSources(rule_score=40.0, fired_rules=[(MIXER, 40.0)],
                      graph_score=76.0, label=label)
    d = decide(src, decision_cfg)
    assert d.level == "HIGH"
    assert d.sources["suppressed_by_trust"] is False


@pytest.mark.parametrize("label", ["exchange", "contract"])
def test_trusted_label_does_not_suppress_hard_signal(decision_cfg, label):
    d = decide(RiskSources(hard_signals=[SANCTION], ml_score=100.0, label=label),
               decision_cfg)
    assert d.level == "CRITICAL"
    assert d.sources["suppressed_by_trust"] is False


# --------------------------------------------------------------------------
# Опциональность графа и объяснимость
# --------------------------------------------------------------------------
def test_graph_absent_does_not_break_logic(decision_cfg):
    """graph_score = None (модуль не считался) — система работает как раньше."""
    d = decide(RiskSources(ml_score=85.0, graph_score=None), decision_cfg)
    assert d.level == "MEDIUM"
    assert d.sources["graph"]["available"] is False


def test_no_signals_is_low_with_high_confidence(decision_cfg):
    d = decide(RiskSources(), decision_cfg)
    assert d.level == "LOW"
    assert d.confidence == pytest.approx(0.90)
    assert d.reasons  # объяснение есть всегда


def test_decision_is_serialisable_and_explains_itself(decision_cfg):
    """Решение всегда объяснимо: уровень, уверенность, причины, вклад источников."""
    d = decide(RiskSources(hard_signals=[SANCTION], rule_score=50.0,
                           fired_rules=[(MIXER, 40.0), ("Большая сумма", 10.0)],
                           ml_score=80.0, graph_score=75.0), decision_cfg)
    payload = d.to_json()
    assert payload["level"] == "CRITICAL"
    assert 0.0 <= payload["confidence"] <= 1.0
    assert payload["reasons"], "решение без причин непригодно для аналитика"
    for key in ("hard_signal", "rule", "ml", "graph", "independent_high_sources"):
        assert key in payload["sources"]


def test_confidence_grows_with_agreement(decision_cfg):
    """Уверенность — согласованность источников, а не выдуманная вероятность."""
    one = decide(RiskSources(ml_score=85.0), decision_cfg).confidence
    two = decide(RiskSources(ml_score=85.0, graph_score=85.0), decision_cfg).confidence
    three = decide(RiskSources(rule_score=80.0, fired_rules=[(MIXER, 80.0)],
                               ml_score=85.0, graph_score=85.0), decision_cfg).confidence
    assert one < two < three
