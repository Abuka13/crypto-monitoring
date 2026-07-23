"""Правила Rule Engine: условия срабатывания.

Уровень риска определяет Decision Engine (risk/decision.py), а не эти правила.

Балл и вкл/выкл правила — в таблице `rule`; условие — здесь. Связь по имени
(реестры TX_RULES / WALLET_RULES): калибровка в БД, логика в коде.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from ..config import RiskConfig

# Имена правил (совпадают с rule.name в БД)
RULE_LARGE_AMOUNT = "Большая сумма"
RULE_MIXER = "Связь с миксером"
RULE_SANCTIONED = "Санкционный адрес"
RULE_NEW_WALLET = "Новый кошелёк"
RULE_HIGH_FREQUENCY = "Высокая частота"
RULE_STRUCTURING = "Дробление сумм"

# Коды меток кошельков (wallet.label). Метка "mixer" — технический факт,
# "sanctioned" — регуляторный статус (OFAC SDN); это независимые вещи.
LABEL_MIXER = "mixer"
LABEL_EXCHANGE = "exchange"
LABEL_SANCTIONED = "sanctioned"
LABEL_FRAUD = "fraud"

# risk_level -> alert.level (lower)
_ALERT_LEVEL = {"LOW": "low", "MEDIUM": "medium", "HIGH": "high", "CRITICAL": "critical"}


def alert_level_from_risk_level(risk_level: str) -> str:
    return _ALERT_LEVEL[risk_level]


# ---- Данные, к которым применяются правила ----
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
    timestamps: list[datetime]   # время всех tx кошелька
    amounts: list[int]           # суммы всех tx, wei


# ---- Условия правил уровня транзакции: (facts, cfg) -> bool ----
def _tx_large_amount(tx: TxFacts, cfg: RiskConfig) -> bool:
    return tx.amount_wei >= cfg.large_amount_threshold_wei


def _tx_mixer(tx: TxFacts, cfg: RiskConfig) -> bool:
    return LABEL_MIXER in (tx.sender_label, tx.receiver_label)


def _tx_sanctioned(tx: TxFacts, cfg: RiskConfig) -> bool:
    return LABEL_SANCTIONED in (tx.sender_label, tx.receiver_label)


TX_RULES = {
    RULE_LARGE_AMOUNT: _tx_large_amount,
    RULE_MIXER: _tx_mixer,
    RULE_SANCTIONED: _tx_sanctioned,
}


# ---- Условия правил уровня кошелька: (facts, cfg) -> bool ----
def _wallet_new(w: WalletFacts, cfg: RiskConfig) -> bool:
    """Недавно создан + крупный оборот. Биржи исключены (это не новые адреса)."""
    if w.label == LABEL_EXCHANGE:
        return False
    if w.first_seen_at is None:
        return False
    age = datetime.now(timezone.utc) - w.first_seen_at
    if age > timedelta(days=cfg.new_wallet_max_age_days):
        return False
    return sum(w.amounts) >= cfg.large_amount_threshold_wei


def _wallet_high_frequency(w: WalletFacts, cfg: RiskConfig) -> bool:
    """>= N транзакций в скользящем окне. Биржи исключены (легитимный поток)."""
    if w.label == LABEL_EXCHANGE:
        return False
    if len(w.timestamps) < cfg.high_frequency_count:
        return False
    window = timedelta(hours=cfg.high_frequency_window_hours)
    ts = sorted(w.timestamps)
    start = 0
    for end in range(len(ts)):
        while ts[end] - ts[start] > window:
            start += 1
        if end - start + 1 >= cfg.high_frequency_count:
            return True
    return False


def _wallet_structuring(w: WalletFacts, cfg: RiskConfig) -> bool:
    """>= N мелких ненулевых операций (structuring). Биржи исключены."""
    if w.label == LABEL_EXCHANGE:
        return False
    small = sum(
        1 for a in w.amounts if 0 < a <= cfg.structuring_small_amount_wei
    )
    return small >= cfg.structuring_min_count


WALLET_RULES = {
    RULE_NEW_WALLET: _wallet_new,
    RULE_HIGH_FREQUENCY: _wallet_high_frequency,
    RULE_STRUCTURING: _wallet_structuring,
}
