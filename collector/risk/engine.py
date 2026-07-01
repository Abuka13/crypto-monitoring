"""Оркестрация Rule Engine.

Шаги 2–4 из docs/architecture.md:
  - применяем активные правила к транзакциям и кошелькам;
  - rule_score = сумма баллов сработавших правил; ml_score = 0; final = rule_score;
  - пишем НОВУЮ строку в transaction_risk / wallet_risk (история, не перезапись);
  - для кошелька обновляем wallet.risk_score и is_flagged;
  - при final_score >= HIGH (50) создаём alert с причиной из сработавших правил.

Две точки входа:
  - score_risk(conn, cfg)                  — пересчитать ВСЮ базу;
  - score_block(conn, cfg, net, block)     — инкрементально, только данные блока
                                             (для конвейера слежения --follow --score).
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


@dataclass
class RiskStats:
    tx_evaluated: int = 0
    tx_risk_rows: int = 0
    tx_alerts: int = 0            # новые алерты по транзакциям
    tx_alerts_updated: int = 0    # обновлённые (дедуп: активный уже был)
    wallets_evaluated: int = 0
    wallet_risk_rows: int = 0
    wallet_alerts: int = 0        # новые алерты по кошелькам
    wallet_alerts_updated: int = 0
    wallets_flagged: int = 0
    skipped_rules: list[str] = field(default_factory=list)

    def __str__(self) -> str:
        return (
            f"транзакций оценено={self.tx_evaluated}, "
            f"оценок tx={self.tx_risk_rows}, алертов по tx (нов/обновл)={self.tx_alerts}/{self.tx_alerts_updated}; "
            f"кошельков оценено={self.wallets_evaluated}, "
            f"оценок wallet={self.wallet_risk_rows}, "
            f"алертов по wallet (нов/обновл)={self.wallet_alerts}/{self.wallet_alerts_updated}, "
            f"помечено кошельков={self.wallets_flagged}"
        )


def _reason(fired: list[tuple[str, Decimal]]) -> str:
    return "; ".join(f"{name} (+{score})" for name, score in fired)


def _emit_or_refresh_alert(conn, *, target_type, object_id, risk_id, title, description, level) -> str:
    """Создать алерт, либо обновить существующий активный (дедуп по объекту).

    Один активный (open/in_progress) алерт на объект: если он уже есть — обновляем
    его свежей оценкой, а не плодим дубль. Новый алерт появится только после того,
    как предыдущий закрыт (closed/false_positive). Возвращает 'created' | 'updated'.
    """
    if target_type == "wallet":
        active = db.find_active_alert_for_wallet(conn, object_id)
    else:
        active = db.find_active_alert_for_transaction(conn, object_id)

    if active is not None:
        db.refresh_alert(
            conn, alert_id=active, target_type=target_type, risk_id=risk_id,
            title=title, description=description, level=level,
        )
        return "updated"

    db.insert_alert(
        conn, target_type=target_type, title=title, description=description, level=level,
        transaction_risk_id=risk_id if target_type == "transaction" else None,
        wallet_risk_id=risk_id if target_type == "wallet" else None,
    )
    return "created"


def _load_rules(conn, stats: RiskStats):
    active = db.get_active_rules(conn)
    tx_rules = [r for r in active if r.name in rules.TX_RULES]
    wallet_rules = [r for r in active if r.name in rules.WALLET_RULES]
    for r in active:
        if r.name not in rules.TX_RULES and r.name not in rules.WALLET_RULES:
            if r.name not in stats.skipped_rules:
                stats.skipped_rules.append(r.name)
            log.warning("Для правила '%s' нет реализации условия — пропущено", r.name)
    return tx_rules, wallet_rules


# ----------------------------------------------------------------------
# Полный пересчёт по всей базе
# ----------------------------------------------------------------------
def score_risk(conn, cfg: RiskConfig) -> RiskStats:
    stats = RiskStats()
    tx_rules, wallet_rules = _load_rules(conn, stats)
    log.info("Активных правил: tx=%d, wallet=%d", len(tx_rules), len(wallet_rules))

    _score_transaction_rows(conn, cfg, tx_rules, db.get_transactions_for_scoring(conn), stats)
    _score_wallet_rows(conn, cfg, wallet_rules, db.get_wallets_for_scoring(conn), stats)

    conn.commit()
    return stats


# ----------------------------------------------------------------------
# Инкрементальный пересчёт: только данные одного блока
# ----------------------------------------------------------------------
def score_block(conn, cfg: RiskConfig, network_id: int, block_number: int) -> RiskStats:
    """Оценить риск только по транзакциям блока и затронутым им кошелькам.

    Не пересчитывает всю базу — поэтому пригоден для конвейера реального времени
    (--follow --score). Кошельки оцениваются по своей полной истории, но в выборку
    попадают лишь участники этого блока.
    """
    stats = RiskStats()
    tx_rules, wallet_rules = _load_rules(conn, stats)

    tx_rows = db.get_transactions_for_scoring_by_block(conn, network_id, block_number)
    _score_transaction_rows(conn, cfg, tx_rules, tx_rows, stats)

    wallet_ids = db.get_affected_wallet_ids_by_block(conn, network_id, block_number)
    wallet_rows = db.get_wallets_for_scoring_by_ids(conn, wallet_ids)
    _score_wallet_rows(conn, cfg, wallet_rules, wallet_rows, stats)

    conn.commit()
    return stats


# ----------------------------------------------------------------------
# Общие помощники (используются и полным, и инкрементальным расчётом)
# ----------------------------------------------------------------------
def _score_transaction_rows(conn, cfg, tx_rules, rows, stats: RiskStats) -> None:
    for tx_id, amount, sender_label, receiver_label in rows:
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
            outcome = _emit_or_refresh_alert(
                conn, target_type="transaction", object_id=tx_id, risk_id=risk_id,
                title=f"Рискованная транзакция: {risk_level} ({final_score})",
                description=f"Сработавшие правила: {_reason(fired)}",
                level=rules.alert_level_from_risk_level(risk_level),
            )
            if outcome == "created":
                stats.tx_alerts += 1
            else:
                stats.tx_alerts_updated += 1


def _score_wallet_rows(conn, cfg, wallet_rules, wallets, stats: RiskStats) -> None:
    for wallet_id, address, first_seen_at, label in wallets:
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
            outcome = _emit_or_refresh_alert(
                conn, target_type="wallet", object_id=wallet_id, risk_id=risk_id,
                title=f"Рискованный кошелёк {address[:12]}…: {risk_level} ({final_score})",
                description=f"Сработавшие правила: {_reason(fired)}",
                level=rules.alert_level_from_risk_level(risk_level),
            )
            if outcome == "created":
                stats.wallet_alerts += 1
            else:
                stats.wallet_alerts_updated += 1
