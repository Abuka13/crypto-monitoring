"""Decision Engine — принятие решения об уровне риска.

Уровень определяется не одной формулой, а решающей логикой над НЕЗАВИСИМЫМИ
источниками с учётом их приоритета:

    Hard Signals  ->  Rule Engine  ->  Graph Analysis  ->  AI Engine

Ключевые инварианты:
- источником считается МОДУЛЬ (Rule / ML / Graph), а не отдельное правило внутри
  модуля: несколько сработавших правил — это ОДИН источник;
- ИИ (и Graph) никогда не снижают уровень, определённый правилами;
- ИИ (и Graph) в одиночку не поднимают уровень выше MEDIUM;
- Hard Signal (санкции/blacklist/подтверждённый мошенник) -> сразу CRITICAL.

Все пороги и списки — в DecisionConfig (.env), не в коде.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from ..config import DecisionConfig

LEVELS = ["LOW", "MEDIUM", "HIGH", "CRITICAL"]
_ORDER = {lvl: i for i, lvl in enumerate(LEVELS)}

# Человекочитаемые названия Hard Signal по коду метки.
_HARD_LABEL_TEXT = {
    "sanctioned": "Санкционный адрес",
    "blacklist": "Адрес в чёрном списке",
    "fraud": "Подтверждённый мошеннический адрес",
}


def _max_level(a: str, b: str) -> str:
    return a if _ORDER[a] >= _ORDER[b] else b


@dataclass
class RiskSources:
    """Сырые сигналы от независимых источников (до принятия решения)."""

    # Hard Signals: список (метка, источник метки, к кому относится)
    hard_signals: list[tuple[str, str | None, str]] = field(default_factory=list)
    # Rule Engine
    rule_score: float = 0.0
    fired_rules: list[tuple[str, float]] = field(default_factory=list)
    # AI Engine (None — модель не применялась)
    ml_score: float | None = None
    ml_explanation: str | None = None
    # Graph Analysis (None — модуль ещё не реализован)
    graph_score: float | None = None
    graph_explanation: str | None = None
    # Метка объекта (для доверенных сущностей вроде бирж)
    label: str | None = None


@dataclass
class Decision:
    """Результат: уровень, уверенность, причины и вклад каждого источника."""

    level: str
    confidence: float
    reasons: list[str]
    sources: dict

    def to_json(self) -> dict:
        return {
            "level": self.level,
            "confidence": round(self.confidence, 2),
            "reasons": self.reasons,
            "sources": self.sources,
        }


def _rule_only_level(rule_score: float, fired_names: set[str], cfg: DecisionConfig) -> str:
    """Уровень, обусловленный ТОЛЬКО правилами — нижняя граница (ИИ её не снижает)."""
    if rule_score >= cfg.rule_high:
        return "HIGH"
    if rule_score >= cfg.rule_medium or (fired_names & cfg.strong_rules):
        return "MEDIUM"
    return "LOW"


def decide(src: RiskSources, cfg: DecisionConfig) -> Decision:
    """Принять решение об уровне риска по независимым источникам."""
    fired_names = {name for name, _ in src.fired_rules}
    strong_fired = sorted(fired_names & cfg.strong_rules)

    # --- Признаки «высокого сигнала» по каждому модулю (модуль = один источник) ---
    rule_high = src.rule_score >= cfg.rule_high
    ml_high = src.ml_score is not None and src.ml_score >= cfg.ml_high
    graph_high = src.graph_score is not None and src.graph_score >= cfg.graph_high
    high_sources = [n for n, ok in
                    (("rule", rule_high), ("ml", ml_high), ("graph", graph_high)) if ok]
    n_high = len(high_sources)
    has_hard = bool(src.hard_signals)

    # --- Решающая логика (по приоритету источников) ---
    if has_hard:
        level = "CRITICAL"
    elif src.rule_score >= cfg.rule_critical and n_high >= 2:
        level = "CRITICAL"
    elif rule_high or n_high >= 2 or (strong_fired and (ml_high or graph_high)):
        level = "HIGH"
    elif (src.rule_score >= cfg.rule_medium or strong_fired or ml_high or graph_high):
        level = "MEDIUM"
    else:
        level = "LOW"

    # --- Ограничения на ИИ и Graph ---
    # 1) ИИ/Graph в одиночку (без правил и Hard Signal) — максимум MEDIUM.
    if not has_hard and not rule_high and not strong_fired and _ORDER[level] > _ORDER["MEDIUM"]:
        level = "MEDIUM"
    # 2) ИИ никогда не снижает уровень, обусловленный правилами.
    level = _max_level(level, _rule_only_level(src.rule_score, fired_names, cfg))

    # 3) Доверенная сущность (напр. биржа): статистическая аномалия ИИ/графа
    #    сама по себе не повод для сигнала — их поведение экстремально по природе.
    #    Правила и Hard Signals продолжают действовать в полном объёме.
    trusted = src.label in cfg.trusted_labels
    suppressed = False
    if (trusted and not has_hard and not rule_high and not strong_fired
            and src.rule_score < cfg.rule_medium):
        level = "LOW"
        suppressed = True

    reasons = _build_reasons(src, cfg, strong_fired)
    if suppressed:
        reasons = [f"Известная легитимная сущность (метка «{src.label}») — "
                   f"аномалия ИИ/графа без срабатывания правил не считается сигналом"]
    confidence = _confidence(has_hard, n_high, level)
    sources = {
        "hard_signal": {
            "active": has_hard,
            "items": [{"label": lb, "source": s, "target": tgt}
                      for lb, s, tgt in src.hard_signals],
        },
        "rule": {"score": round(src.rule_score, 2), "high": rule_high,
                 "fired": [{"name": n, "score": round(s, 2)} for n, s in src.fired_rules],
                 "strong": strong_fired},
        "ml": {"score": src.ml_score, "high": ml_high,
               "available": src.ml_score is not None, "explanation": src.ml_explanation},
        "graph": {"score": src.graph_score, "high": graph_high,
                  "available": src.graph_score is not None,
                  "explanation": src.graph_explanation},
        "independent_high_sources": high_sources,
        "trusted_entity": trusted,
        "suppressed_by_trust": suppressed,
    }
    return Decision(level=level, confidence=confidence, reasons=reasons, sources=sources)


def _build_reasons(src: RiskSources, cfg: DecisionConfig, strong_fired: list[str]) -> list[str]:
    """Причины решения человеческим языком (по приоритету источников)."""
    reasons: list[str] = []
    for label, source, target in src.hard_signals:
        text = _HARD_LABEL_TEXT.get(label, f"Метка «{label}»")
        who = f" — {target}" if target else ""
        reasons.append(f"{text}{who}" + (f" (источник: {source})" if source else ""))

    for name, score in src.fired_rules:
        mark = " [сильное правило]" if name in cfg.strong_rules else ""
        reasons.append(f"Правило: {name} (+{score:g}){mark}")

    if src.ml_score is not None and src.ml_score > 0:
        tail = f" — {src.ml_explanation}" if src.ml_explanation else ""
        reasons.append(f"ML: вероятность нетипичного поведения {int(src.ml_score)}%{tail}")

    if src.graph_score is not None:
        tail = f" — {src.graph_explanation}" if src.graph_explanation else ""
        reasons.append(f"Граф: подозрительные связи {int(src.graph_score)}%{tail}")

    return reasons or ["Существенных признаков риска не обнаружено"]


def _confidence(has_hard: bool, n_high: int, level: str) -> float:
    """Уверенность = согласованность независимых источников (не выдуманная вероятность).

    Hard Signal — документально подтверждённый факт (санкционный список), поэтому
    даёт максимальную уверенность. В остальных случаях уверенность растёт с числом
    независимых модулей, давших высокий сигнал: один источник можно объяснить
    случайностью, согласие двух и более — вряд ли. Если сигналов нет и решение LOW,
    источники тоже СОГЛАСНЫ (риска нет) — уверенность высокая. Промежуточный случай
    (средний rule_score без подтверждений) — наименее уверенный.
    """
    if has_hard:
        return 0.99
    if n_high >= 3:
        return 0.95
    if n_high == 2:
        return 0.85
    if n_high == 1:
        return 0.60
    return 0.90 if level == "LOW" else 0.50
