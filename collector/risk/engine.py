"""Оркестрация Rule Engine (шаги 2–4 из docs/architecture.md).

Применяет правила -> пишет оценку риска (история) -> при уровне не LOW создаёт/
обновляет alert. Точки входа: score_risk (вся база), score_block (один блок).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from decimal import Decimal

from .. import db
from ..config import DecisionConfig, RiskConfig
from . import rules
from .decision import RiskSources, decide
from .rules import TxFacts, WalletFacts

log = logging.getLogger(__name__)


@dataclass
class RiskStats:
    tx_evaluated: int = 0
    tx_risk_rows: int = 0
    tx_alerts: int = 0            # новые
    tx_alerts_updated: int = 0    # обновлённые (дедуп)
    wallets_evaluated: int = 0
    wallet_risk_rows: int = 0
    wallet_alerts: int = 0
    wallet_alerts_updated: int = 0
    wallets_flagged: int = 0
    wallets_ml_scored: int = 0       # кошельков с ML-оценкой (есть признаки)
    wallets_graph_scored: int = 0    # кошельков с graph-оценкой (есть граф-признаки)
    skipped_rules: list[str] = field(default_factory=list)

    def __str__(self) -> str:
        return (
            f"транзакций оценено={self.tx_evaluated}, "
            f"оценок tx={self.tx_risk_rows}, алертов по tx (нов/обновл)={self.tx_alerts}/{self.tx_alerts_updated}; "
            f"кошельков оценено={self.wallets_evaluated}, "
            f"оценок wallet={self.wallet_risk_rows}, "
            f"алертов по wallet (нов/обновл)={self.wallet_alerts}/{self.wallet_alerts_updated}, "
            f"помечено кошельков={self.wallets_flagged}, "
            f"ML-оценок={self.wallets_ml_scored}, граф-оценок={self.wallets_graph_scored}"
        )


def reason_key(sources: dict, dcfg=None) -> str:
    """Ключ причины — ТОЖДЕСТВО находки: hard:<метка> | rule:<имя>.

    Принимает `decision.sources` (или тот же словарь из сохранённого JSONB), чтобы
    движок и миграция старых алертов считали ключ одинаково.

    Берётся не весь набор сработавшего, а ГЛАВНАЯ причина по приоритету
    Hard Signal -> сильное правило -> обычные правила. Иначе находка дробится на
    ровном месте: 279 переводов с санкционным адресом и ещё 19 таких же, но
    крупных, дали бы два разных алерта, хотя это одно и то же открытие.

    ML и граф в ключ не входят: это подтверждающие сигналы, они колеблются от
    прогона к прогону и плодили бы новые алерты. Санкции и дробление дают разные
    ключи — значит, остаются разными алертами, как и требуется.
    """
    sources = sources or {}
    hard = sorted({it["label"]
                   for it in (sources.get("hard_signal") or {}).get("items", [])})
    if hard:
        return "|".join(f"hard:{h}" for h in hard)

    fired = sorted({r["name"] for r in (sources.get("rule") or {}).get("fired", [])})
    strong = sorted(set(fired) & set(dcfg.strong_rules)) if dcfg else []
    names = strong or fired
    return "|".join(f"rule:{n}" for n in names) or "ml_graph_only"


_CAUSE_TEXT = {
    "sanctioned": "связь с санкционным адресом",
    "blacklist": "адрес в чёрном списке",
    "fraud": "связь с мошенническим адресом",
    "mixer": "связь с миксером",
}


def _cause_phrase(reason: str) -> str:
    """Причина человеческим языком для заголовка (по ключу, а не по тексту решения)."""
    parts = []
    for token in reason.split("|"):
        kind, _, value = token.partition(":")
        if kind == "hard":
            parts.append(_CAUSE_TEXT.get(value, f"метка «{value}»"))
        elif kind == "rule":
            parts.append(_CAUSE_TEXT.get(value.lower(), value.lower()))
    return ", ".join(parts) or "аномальное поведение"


def _fmt_period(first_at, last_at) -> str:
    if not first_at or not last_at:
        return ""
    fmt = "%d.%m.%Y"
    a, b = first_at.strftime(fmt), last_at.strftime(fmt)
    return a if a == b else f"{a}–{b}"


def _entity_title(address: str, reason: str, summary=None) -> str:
    """«Кошелёк 0xABC… — связь с санкционным адресом: 300 транзакций, 01.01–02.02»."""
    head = f"Кошелёк {address[:10]}… — {_cause_phrase(reason)}"
    if not summary or not summary[0]:
        return head[:200]
    count, first_at, last_at, _total = summary
    period = _fmt_period(first_at, last_at)
    tail = f": {count} транзакц." + (f", {period}" if period else "")
    return (head + tail)[:200]


def _emit_entity_alert(conn, *, wallet_id, address, reason, target_type, risk_id,
                       description, level, evidence_tx_id=None,
                       evidence_wallet_id=None) -> str:
    """Алерт на связку (кошелёк, причина). Повторное событие с той же причиной не
    плодит сигнал, а добавляется в доказательства. -> 'created'|'updated'."""
    active = db.find_active_entity_alert(conn, wallet_id, reason)
    title = _entity_title(address, reason)

    if active is None:
        alert_id = db.insert_entity_alert(
            conn, wallet_id=wallet_id, reason_key=reason, target_type=target_type,
            title=title, description=description, level=level,
            transaction_risk_id=risk_id if target_type == "transaction" else None,
            wallet_risk_id=risk_id if target_type == "wallet" else None,
        )
        outcome = "created"
    else:
        alert_id = active[0]
        db.refresh_entity_alert(
            conn, alert_id=alert_id, target_type=target_type, risk_id=risk_id,
            title=title, description=description, level=level,
        )
        outcome = "updated"

    # Заголовок с числом доказательств можно проставить только ПОСЛЕ пересчёта.
    if evidence_tx_id is not None:
        db.add_alert_evidence(conn, alert_id, evidence_tx_id)
    elif evidence_wallet_id is not None:
        db.add_wallet_evidence(conn, alert_id, evidence_wallet_id)
    else:
        return outcome

    summary = db.recalc_alert_evidence(conn, alert_id)
    db.set_alert_title(conn, alert_id, _entity_title(address, reason, summary))
    return outcome


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


# ---- Полный пересчёт по всей базе ----
def score_risk(conn, cfg: RiskConfig, model=None, dcfg: DecisionConfig | None = None) -> RiskStats:
    """Полный расчёт (tx + кошельки). Уровень риска определяет Decision Engine.
    model (AnomalyModel) опционален: без него ИИ просто не участвует в решении."""
    dcfg = dcfg or DecisionConfig.load()
    stats = RiskStats()
    tx_rules, wallet_rules = _load_rules(conn, stats)
    log.info("Активных правил: tx=%d, wallet=%d; ML=%s",
             len(tx_rules), len(wallet_rules), "вкл" if model else "выкл")

    _score_transaction_rows(conn, cfg, dcfg, tx_rules,
                            db.get_transactions_for_scoring(conn), stats)

    fmap = db.get_wallet_features_map(conn) if model else {}
    gmap = db.get_wallet_graph_map(conn)  # graph подмешивается, если посчитан
    _score_wallet_rows(conn, cfg, dcfg, wallet_rules, db.get_wallets_for_scoring(conn),
                       stats, model=model, features_map=fmap, graph_map=gmap)

    conn.commit()
    return stats


# ---- Инкрементальный пересчёт: только данные одного блока ----
def score_block(conn, cfg: RiskConfig, network_id: int, block_number: int,
                model=None, dcfg: DecisionConfig | None = None) -> RiskStats:
    """Риск только по tx блока и затронутым кошелькам (для --follow --score)."""
    dcfg = dcfg or DecisionConfig.load()
    stats = RiskStats()
    tx_rules, wallet_rules = _load_rules(conn, stats)

    tx_rows = db.get_transactions_for_scoring_by_block(conn, network_id, block_number)
    _score_transaction_rows(conn, cfg, dcfg, tx_rules, tx_rows, stats)

    wallet_ids = db.get_affected_wallet_ids_by_block(conn, network_id, block_number)
    wallet_rows = db.get_wallets_for_scoring_by_ids(conn, wallet_ids)
    fmap = db.get_wallet_features_map(conn, wallet_ids) if model else {}
    gmap = db.get_wallet_graph_map(conn, wallet_ids)
    _score_wallet_rows(conn, cfg, dcfg, wallet_rules, wallet_rows, stats,
                       model=model, features_map=fmap, graph_map=gmap)

    conn.commit()
    return stats


# ---- Только кошельки: применить ИИ и/или граф (для --score-anomaly / --score-graph) ----
def score_wallets(conn, cfg: RiskConfig, model=None, dcfg: DecisionConfig | None = None) -> RiskStats:
    """Пересчитать риск всех кошельков. model — опционально (ИИ); граф
    подмешивается автоматически, если посчитан (wallet_graph_features)."""
    dcfg = dcfg or DecisionConfig.load()
    stats = RiskStats()
    _, wallet_rules = _load_rules(conn, stats)
    fmap = db.get_wallet_features_map(conn) if model else {}
    gmap = db.get_wallet_graph_map(conn)
    _score_wallet_rows(conn, cfg, dcfg, wallet_rules, db.get_wallets_for_scoring(conn),
                       stats, model=model, features_map=fmap, graph_map=gmap)
    conn.commit()
    return stats


# ---- Один кошелёк (для скрининга по запросу) ----
def score_one_wallet(conn, cfg: RiskConfig, wallet_id: int, model=None,
                     dcfg: DecisionConfig | None = None,
                     graph_map: dict | None = None) -> RiskStats:
    """Оценить риск одного кошелька тем же путём, что и пакетный расчёт.

    Важно для скрининга: вердикт обязан совпадать с тем, что система скажет об
    этом кошельке в обычном режиме, поэтому переиспользуется _score_wallet_rows,
    а не отдельная копия логики."""
    dcfg = dcfg or DecisionConfig.load()
    stats = RiskStats()
    _, wallet_rules = _load_rules(conn, stats)
    rows = db.get_wallets_for_scoring_by_ids(conn, [wallet_id])
    fmap = db.get_wallet_features_map(conn, [wallet_id]) if model else {}
    gmap = graph_map if graph_map is not None else db.get_wallet_graph_map(conn, [wallet_id])
    _score_wallet_rows(conn, cfg, dcfg, wallet_rules, rows, stats,
                       model=model, features_map=fmap, graph_map=gmap)
    conn.commit()
    return stats


# ---- Общие помощники (полный и инкрементальный расчёт) ----
def _subject_wallet(sender_id, receiver_id, sender_label, receiver_label, dcfg):
    """Сущность, «о которой» находка: участник с триггерящей меткой, иначе отправитель.

    Для транзакции с санкционным получателем находка — про санкционный адрес, а не
    про конкретный перевод; так все переводы с ним схлопываются в один алерт.
    """
    flagged = dcfg.hard_signal_labels | {"mixer"}
    if receiver_label in flagged:
        return receiver_id
    if sender_label in flagged:
        return sender_id
    return sender_id


def _score_transaction_rows(conn, cfg, dcfg, tx_rules, rows, stats: RiskStats) -> None:
    # Адреса нужны только для заголовков алертов — кешируем, чтобы не делать
    # запрос на каждую из десятков тысяч транзакций.
    _addr: dict[int, str] = {}

    def addr_cache(conn, wallet_id: int) -> str:
        if wallet_id not in _addr:
            _addr.update(db.get_wallet_addresses(conn, [wallet_id]))
        return _addr.get(wallet_id, "")

    for (tx_id, amount, sender_label, receiver_label,
         sender_src, receiver_src, sender_id, receiver_id) in rows:
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

        # Hard Signals: метки участников транзакции.
        hard = []
        for lbl, src, who in ((sender_label, sender_src, "отправитель"),
                              (receiver_label, receiver_src, "получатель")):
            if lbl in dcfg.hard_signal_labels:
                hard.append((lbl, src, who))

        # Решение принимает Decision Engine (ML/Graph для транзакций пока нет).
        decision = decide(RiskSources(
            hard_signals=hard,
            rule_score=float(rule_score),
            fired_rules=[(n, float(s)) for n, s in fired],
        ), dcfg)
        risk_level = decision.level
        final_score = rule_score  # справочное значение (совместимость)

        risk_id = db.insert_transaction_risk(
            conn, transaction_id=tx_id, rule_score=rule_score,
            ml_score=Decimal(0), final_score=final_score, risk_level=risk_level,
            graph_score=None, decision=decision.to_json(),
        )
        stats.tx_evaluated += 1
        stats.tx_risk_rows += 1

        if risk_level != "LOW":
            subject = _subject_wallet(sender_id, receiver_id,
                                      sender_label, receiver_label, dcfg)
            outcome = _emit_entity_alert(
                conn, wallet_id=subject, address=addr_cache(conn, subject),
                reason=reason_key(decision.sources, dcfg),
                target_type="transaction", risk_id=risk_id,
                description=" | ".join(decision.reasons),
                level=rules.alert_level_from_risk_level(risk_level),
                evidence_tx_id=tx_id,
            )
            if outcome == "created":
                stats.tx_alerts += 1
            else:
                stats.tx_alerts_updated += 1


def _score_wallet_rows(conn, cfg, dcfg, wallet_rules, wallets, stats: RiskStats,
                       model=None, features_map=None, graph_map=None) -> None:
    features_map = features_map or {}
    graph_map = graph_map or {}
    for wallet_id, address, first_seen_at, label, label_source in wallets:
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

        # ML-аномалия считается только для кошельков с признаками.
        ml_score = Decimal(0)
        ml_value = None
        ml_expl = None
        if model is not None and wallet_id in features_map:
            ml_int, ml_expl = model.score_one(features_map[wallet_id])
            ml_score = Decimal(ml_int)
            ml_value = float(ml_int)
            stats.wallets_ml_scored += 1

        # Граф-аномалия подмешивается, если посчитана (--build-graph).
        graph_value = None
        graph_expl = None
        graph_dec = None
        if wallet_id in graph_map:
            graph_value, graph_expl = graph_map[wallet_id]
            graph_dec = Decimal(str(graph_value))
            stats.wallets_graph_scored += 1

        # Hard Signal по метке кошелька.
        hard = ([(label, label_source, "кошелёк")]
                if label in dcfg.hard_signal_labels else [])

        # Решение принимает Decision Engine (граф — источник наравне с ML).
        decision = decide(RiskSources(
            hard_signals=hard,
            rule_score=float(rule_score),
            fired_rules=[(n, float(s)) for n, s in fired],
            ml_score=ml_value,
            ml_explanation=ml_expl,
            graph_score=graph_value,
            graph_explanation=graph_expl,
            label=label,
        ), dcfg)
        risk_level = decision.level
        is_flagged = risk_level != "LOW"

        # final_score — справочное значение для совместимости (шкала 0–100).
        final_score = (
            Decimal(str(round(cfg.weight_rule * float(rule_score)
                              + cfg.weight_ml * ml_value, 2)))
            if ml_value is not None else rule_score
        )

        risk_id = db.insert_wallet_risk(
            conn, wallet_id=wallet_id, rule_score=rule_score,
            ml_score=ml_score, final_score=final_score, risk_level=risk_level,
            ml_explanation=ml_expl, graph_score=graph_dec, decision=decision.to_json(),
        )
        db.update_wallet_risk_summary(
            conn, wallet_id=wallet_id, risk_score=final_score, is_flagged=is_flagged,
        )
        stats.wallets_evaluated += 1
        stats.wallet_risk_rows += 1
        if is_flagged:
            stats.wallets_flagged += 1

        if risk_level != "LOW":
            outcome = _emit_entity_alert(
                conn, wallet_id=wallet_id, address=address,
                reason=reason_key(decision.sources, dcfg),
                target_type="wallet", risk_id=risk_id,
                description=" | ".join(decision.reasons),
                level=rules.alert_level_from_risk_level(risk_level),
                evidence_wallet_id=wallet_id,
            )
            if outcome == "created":
                stats.wallet_alerts += 1
            else:
                stats.wallet_alerts_updated += 1
