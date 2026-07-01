"""Правила Rule Engine: проверяемые условия + маппинг баллов в уровень риска.

Разделение ответственности:
- таблица `rule` в БД хранит *название*, *балл* (score) и флаг активности;
- здесь живёт *условие* каждого правила (как именно проверять).
Правило из БД связывается с условием по имени (реестры TX_RULES / WALLET_RULES).
Так баллы и включение правил меняются в БД, а логика — в коде.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from ..config import RiskConfig

# --- Имена правил (должны совпадать с rule.name в БД) ---
RULE_LARGE_AMOUNT = "Большая сумма"
RULE_MIXER = "Связь с миксером"
RULE_NEW_WALLET = "Новый кошелёк"
RULE_HIGH_FREQUENCY = "Высокая частота"
RULE_STRUCTURING = "Дробление сумм"

MIXER_LABEL = "миксер"

# Алерт создаётся, если балл ВЫШЕ этого порога (то есть уровень не LOW).
# Балл <= 50 (LOW) остаётся оценкой риска, но алерт не порождает.
ALERT_MIN_SCORE = Decimal(50)

# risk_level (UPPER) -> alert.level (lower). Все четыре уровня поддержаны схемой.
_ALERT_LEVEL = {"LOW": "low", "MEDIUM": "medium", "HIGH": "high", "CRITICAL": "critical"}


def level_from_score(score: Decimal) -> str:
    """final_score -> risk_level.

    Границы: 0–50 LOW · 51–70 MEDIUM · 71–80 HIGH · 81+ CRITICAL.
    (50→LOW, 70→MEDIUM, 80→HIGH, 81→CRITICAL.)
    """
    if score > 80:
        return "CRITICAL"
    if score > 70:
        return "HIGH"
    if score > 50:
        return "MEDIUM"
    return "LOW"


def alert_creation_needed(risk_level: str) -> bool:
    """Алерт создаётся для всех уровней, кроме LOW."""
    return risk_level != "LOW"


def alert_level_from_risk_level(risk_level: str) -> str:
    """risk_level (UPPER) -> alert.level (lower, включая critical)."""
    return _ALERT_LEVEL[risk_level]


# ----------------------------------------------------------------------
# Данные, к которым применяются правила
# ----------------------------------------------------------------------
@dataclass(frozen=True)
class TxFacts:
    tx_id: int
    amount_wei: int
    sender_label: str | None
    receiver_label: str | None


@dataclass(frozen=True)
class WalletFacts:
    wallet_id: int
    address: str
    first_seen_at: datetime | None
    label: str | None
    timestamps: list[datetime]   # время всех транзакций кошелька
    amounts: list[int]           # суммы всех транзакций кошелька, wei


# ----------------------------------------------------------------------
# Условия правил уровня транзакции: (facts, cfg) -> bool
# ----------------------------------------------------------------------
def _tx_large_amount(tx: TxFacts, cfg: RiskConfig) -> bool:
    return tx.amount_wei >= cfg.large_amount_threshold_wei


def _tx_mixer(tx: TxFacts, cfg: RiskConfig) -> bool:
    return MIXER_LABEL in (tx.sender_label, tx.receiver_label)


TX_RULES = {
    RULE_LARGE_AMOUNT: _tx_large_amount,
    RULE_MIXER: _tx_mixer,
}


# ----------------------------------------------------------------------
# Условия правил уровня кошелька: (facts, cfg) -> bool
# ----------------------------------------------------------------------
def _wallet_new(w: WalletFacts, cfg: RiskConfig) -> bool:
    """Кошелёк создан недавно и при этом ворочает крупными суммами."""
    if w.first_seen_at is None:
        return False
    age = datetime.now(timezone.utc) - w.first_seen_at
    if age > timedelta(days=cfg.new_wallet_max_age_days):
        return False
    return sum(w.amounts) >= cfg.large_amount_threshold_wei


def _wallet_high_frequency(w: WalletFacts, cfg: RiskConfig) -> bool:
    """Много транзакций в скользящем окне фиксированной ширины."""
    if len(w.timestamps) < cfg.high_frequency_count:
        return False
    window = timedelta(hours=cfg.high_frequency_window_hours)
    ts = sorted(w.timestamps)
    # Скользящее окно: для каждого начала считаем, сколько операций попало в окно.
    start = 0
    for end in range(len(ts)):
        while ts[end] - ts[start] > window:
            start += 1
        if end - start + 1 >= cfg.high_frequency_count:
            return True
    return False


def _wallet_structuring(w: WalletFacts, cfg: RiskConfig) -> bool:
    """Дробление: много мелких (но ненулевых) операций — паттерн structuring."""
    small = sum(
        1 for a in w.amounts if 0 < a <= cfg.structuring_small_amount_wei
    )
    return small >= cfg.structuring_min_count


WALLET_RULES = {
    RULE_NEW_WALLET: _wallet_new,
    RULE_HIGH_FREQUENCY: _wallet_high_frequency,
    RULE_STRUCTURING: _wallet_structuring,
}
