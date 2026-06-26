"""Правила Rule Engine: проверяемые условия + маппинг баллов в уровень риска.

Разделение ответственности:
- таблица `rule` в БД хранит *название*, *балл* (score) и флаг активности;
- здесь живёт *условие* каждого правила (как именно проверять).
Правило из БД связывается с условием по имени (реестры TX_RULES / WALLET_RULES).
Так баллы и включение правил меняются в БД, а логика — в коде.

Демо-правило «Большая сумма (тест)» намеренно имеет низкий порог, чтобы на уже
собранных данных (адрес Виталика, 2015 г.) сработать и показать конвейер
риск → алерт. Боевое «Большая сумма» использует высокий порог из конфига.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from ..config import RiskConfig

# --- Имена правил (должны совпадать с rule.name в БД) ---
RULE_LARGE_AMOUNT = "Большая сумма"
RULE_LARGE_AMOUNT_TEST = "Большая сумма (тест)"
RULE_MIXER = "Связь с миксером"
RULE_NEW_WALLET = "Новый кошелёк"
RULE_HIGH_FREQUENCY = "Высокая частота"
RULE_STRUCTURING = "Дробление сумм"

MIXER_LABEL = "миксер"

# Алерт создаётся при final_score >= этого порога (граница уровня HIGH).
HIGH_THRESHOLD = Decimal(50)

# В таблице alert уровень в нижнем регистре и без CRITICAL — маппим из risk_level.
_ALERT_LEVEL = {"LOW": "low", "MEDIUM": "medium", "HIGH": "high", "CRITICAL": "high"}


def level_from_score(score: Decimal) -> str:
    """final_score -> risk_level: 0–25 LOW, 25–50 MEDIUM, 50–75 HIGH, 75+ CRITICAL."""
    if score >= 75:
        return "CRITICAL"
    if score >= 50:
        return "HIGH"
    if score >= 25:
        return "MEDIUM"
    return "LOW"


def alert_level_from_risk_level(risk_level: str) -> str:
    """risk_level (UPPER, c CRITICAL) -> alert.level (lower, без critical)."""
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


def _tx_large_amount_test(tx: TxFacts, cfg: RiskConfig) -> bool:
    return tx.amount_wei >= cfg.large_amount_test_threshold_wei


def _tx_mixer(tx: TxFacts, cfg: RiskConfig) -> bool:
    return MIXER_LABEL in (tx.sender_label, tx.receiver_label)


TX_RULES = {
    RULE_LARGE_AMOUNT: _tx_large_amount,
    RULE_LARGE_AMOUNT_TEST: _tx_large_amount_test,
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
