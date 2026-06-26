"""Оркестрация Rule Engine.

Шаги 2–4 из docs/architecture.md:
  - применяем активные правила к транзакциям и кошелькам;
  - rule_score = сумма баллов сработавших правил; ml_score = 0; final = rule_score;
  - пишем НОВУЮ строку в transaction_risk / wallet_risk (история, не перезапись);
  - для кошелька обновляем wallet.risk_score и is_flagged;
  - при final_score >= HIGH (50) создаём alert с причиной из сработавших правил.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from decimal import Decimal

from .. import db
from ..config import RiskConfig
from . import rules
from .rules import TxFacts, WalletFacts

log = logging.getLogger(__name__)

# Демо-правило: низкий порог, заведомо срабатывает на собранных данных и даёт
# балл >= HIGH, чтобы показать весь конвейер риск → алерт. Балл 60 → уровень HIGH.
_DEMO_RULE_NAME = rules.RULE_LARGE_AMOUNT_TEST
_DEMO_RULE_SCORE = Decimal("60.00")
_DEMO_RULE_DESCRIPTION = (
    "ДЕМО: сумма превышает заниженный тестовый порог "
    "(RISK_LARGE_AMOUNT_TEST_WEI) — для наглядной проверки конвейера риск → алерт"
)


@dataclass
class RiskStats:
    tx_evaluated: int = 0
    tx_risk_rows: int = 0
    tx_alerts: int = 0
    wallets_evaluated: int = 0
    wallet_risk_rows: int = 0
    wallet_alerts: int = 0
    wallets_flagged: int = 0
    skipped_rules: list[str] = field(default_factory=list)

    def __str__(self) -> str:
        return (
            f"транзакций оценено={self.tx_evaluated}, "
            f"оценок tx={self.tx_risk_rows}, алертов по tx={self.tx_alerts}; "
            f"кошельков оценено={self.wallets_evaluated}, "
            f"оценок wallet={self.wallet_risk_rows}, "
            f"алертов по wallet={self.wallet_alerts}, "
            f"помечено кошельков={self.wallets_flagged}"
        )


def _reason(fired: list[tuple[str, Decimal]]) -> str:
    return "; ".join(f"{name} (+{score})" for name, score in fired)


def score_risk(conn, cfg: RiskConfig) -> RiskStats:
    stats = RiskStats()

    # Гарантируем наличие демо-правила, затем берём ВСЕ активные правила из БД.
    db.ensure_rule(conn, _DEMO_RULE_NAME, _DEMO_RULE_DESCRIPTION, _DEMO_RULE_SCORE)
    active = db.get_active_rules(conn)

    tx_rules = [r for r in active if r.name in rules.TX_RULES]
    wallet_rules = [r for r in active if r.name in rules.WALLET_RULES]
    for r in active:
        if r.name not in rules.TX_RULES and r.name not in rules.WALLET_RULES:
            stats.skipped_rules.append(r.name)
            log.warning("Для правила '%s' нет реализации условия — пропущено", r.name)

    log.info(
        "Активных правил: %d (tx=%d, wallet=%d)",
        len(active), len(tx_rules), len(wallet_rules),
    )

    _score_transactions(conn, cfg, tx_rules, stats)
    _score_wallets(conn, cfg, wallet_rules, stats)

    conn.commit()
    return stats


def _score_transactions(conn, cfg, tx_rules, stats: RiskStats) -> None:
    for tx_id, amount, sender_label, receiver_label in db.get_transactions_for_scoring(conn):
        facts = TxFacts(
            tx_id=tx_id,
            amount_wei=int(amount),
            sender_label=sender_label,
            receiver_label=receiver_label,
        )
        fired = [
            (rule.name, rule.score)
            for rule in tx_rules
            if rules.TX_RULES[rule.name](facts, cfg)
        ]
        rule_score = sum((s for _, s in fired), Decimal(0))
        final_score = rule_score  # ml_score = 0 на первом этапе
        risk_level = rules.level_from_score(final_score)

        risk_id = db.insert_transaction_risk(
            conn, transaction_id=tx_id, rule_score=rule_score,
            ml_score=Decimal(0), final_score=final_score, risk_level=risk_level,
        )
        stats.tx_evaluated += 1
        stats.tx_risk_rows += 1

        if final_score >= rules.HIGH_THRESHOLD:
            db.insert_alert(
                conn,
                target_type="transaction",
                transaction_risk_id=risk_id,
                title=f"Рискованная транзакция: {risk_level} ({final_score})",
                description=f"Сработавшие правила: {_reason(fired)}",
                level=rules.alert_level_from_risk_level(risk_level),
            )
            stats.tx_alerts += 1


def _score_wallets(conn, cfg, wallet_rules, stats: RiskStats) -> None:
    for wallet_id, address, first_seen_at, label in db.get_wallets_for_scoring(conn):
        history = db.get_wallet_tx_history(conn, wallet_id)
        facts = WalletFacts(
            wallet_id=wallet_id,
            address=address,
            first_seen_at=first_seen_at,
            label=label,
            timestamps=[ts for ts, _ in history],
            amounts=[int(a) for _, a in history],
        )
        fired = [
            (rule.name, rule.score)
            for rule in wallet_rules
            if rules.WALLET_RULES[rule.name](facts, cfg)
        ]
        rule_score = sum((s for _, s in fired), Decimal(0))
        final_score = rule_score
        risk_level = rules.level_from_score(final_score)
        is_flagged = final_score >= rules.HIGH_THRESHOLD

        risk_id = db.insert_wallet_risk(
            conn, wallet_id=wallet_id, rule_score=rule_score,
            ml_score=Decimal(0), final_score=final_score, risk_level=risk_level,
        )
        db.update_wallet_risk_summary(
            conn, wallet_id=wallet_id, risk_score=final_score, is_flagged=is_flagged,
        )
        stats.wallets_evaluated += 1
        stats.wallet_risk_rows += 1
        if is_flagged:
            stats.wallets_flagged += 1

        if final_score >= rules.HIGH_THRESHOLD:
            db.insert_alert(
                conn,
                target_type="wallet",
                wallet_risk_id=risk_id,
                title=f"Рискованный кошелёк {address[:12]}…: {risk_level} ({final_score})",
                description=f"Сработавшие правила: {_reason(fired)}",
                level=rules.alert_level_from_risk_level(risk_level),
            )
            stats.wallet_alerts += 1
