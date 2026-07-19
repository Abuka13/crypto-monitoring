"""Расчёт числовых признаков кошелька для ML (Isolation Forest).

Здесь только вычисление и сохранение признаков; сама ML-модель — следующий этап.
Признаки считаются из транзакций кошелька (как отправителя и получателя).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import timedelta

from . import db
from .config import RiskConfig

log = logging.getLogger(__name__)

# Кошельки с меньшим числом транзакций пропускаем — признаки шумны.
DEFAULT_MIN_TX = 5


@dataclass
class FeatureStats:
    processed: int = 0
    skipped_no_tx: int = 0

    def __str__(self) -> str:
        return f"признаки посчитаны для {self.processed} кошельков"


def compute_features(rows: list[tuple], wallet_id: int, cfg: RiskConfig) -> dict | None:
    """Признаки одного кошелька из его транзакций.

    rows: (sender_id, receiver_id, amount, timestamp), отсортированы по времени.
    Возвращает dict колонка->значение или None, если транзакций нет.
    """
    if not rows:
        return None

    tx_total = len(rows)
    tx_in = tx_out = 0
    total_received = total_sent = 0
    amounts: list[int] = []
    timestamps = []
    senders: set[int] = set()      # кто присылал (входящие)
    receivers: set[int] = set()    # кому отправлял (исходящие)
    small_count = zero_count = 0

    small_threshold = cfg.structuring_small_amount_wei

    for sender_id, receiver_id, amount, ts in rows:
        amount = int(amount)
        amounts.append(amount)
        timestamps.append(ts)

        if amount == 0:
            zero_count += 1
        elif amount <= small_threshold:
            small_count += 1

        is_out = sender_id == wallet_id
        is_in = receiver_id == wallet_id
        if is_out:
            tx_out += 1
            total_sent += amount
            if receiver_id != wallet_id:
                receivers.add(receiver_id)
        if is_in:
            tx_in += 1
            total_received += amount
            if sender_id != wallet_id:
                senders.add(sender_id)

    counterparties = senders | receivers
    max_amount = max(amounts)
    avg_amount = sum(amounts) // tx_total  # целочисленно (wei)

    # Временны́е признаки
    first, last = timestamps[0], timestamps[-1]
    active_period_days = (last - first).total_seconds() / 86400.0
    # Частота: делим на период, но не меньше 1 часа (иначе всплеск -> бесконечность).
    denom_days = max(active_period_days, 1.0 / 24.0)
    avg_tx_per_day = tx_total / denom_days
    max_tx_24h = _max_in_window(timestamps, timedelta(hours=24))

    # Транзитность (deposit-and-forward): близость входящего и исходящего объёма.
    # ~1 => сколько пришло, столько и ушло (сквозной поток). Упрощённая оценка;
    # TODO: учесть время удержания (медиана между входящей и следующей исходящей).
    hi = max(total_received, total_sent)
    transit_ratio = (min(total_received, total_sent) / hi) if hi > 0 else 0.0

    return {
        "tx_total": tx_total,
        "tx_in": tx_in,
        "tx_out": tx_out,
        "total_received": total_received,
        "total_sent": total_sent,
        "avg_amount": avg_amount,
        "max_amount": max_amount,
        "in_out_count_ratio": tx_in / max(tx_out, 1),
        "in_out_value_ratio": total_received / max(total_sent, 1),
        "unique_counterparties": len(counterparties),
        "unique_senders": len(senders),
        "unique_receivers": len(receivers),
        "counterparty_spread": len(counterparties) / tx_total,
        "active_period_days": active_period_days,
        "avg_tx_per_day": avg_tx_per_day,
        "max_tx_24h": max_tx_24h,
        "small_tx_ratio": small_count / tx_total,
        "zero_tx_ratio": zero_count / tx_total,
        "transit_ratio": transit_ratio,
    }


def _max_in_window(timestamps: list, window: timedelta) -> int:
    """Макс. число транзакций в любом скользящем окне заданной ширины."""
    ts = sorted(timestamps)
    best = 0
    start = 0
    for end in range(len(ts)):
        while ts[end] - ts[start] > window:
            start += 1
        best = max(best, end - start + 1)
    return best


def compute_all(conn, cfg: RiskConfig, min_tx: int = DEFAULT_MIN_TX) -> FeatureStats:
    """Посчитать и сохранить признаки для всех кошельков с >= min_tx транзакций."""
    stats = FeatureStats()
    wallet_ids = db.get_wallet_ids_for_features(conn, min_tx)
    total = len(wallet_ids)
    log.info("Кошельков к обработке (>=%d tx): %d", min_tx, total)

    for i, wallet_id in enumerate(wallet_ids, 1):
        rows = db.get_wallet_tx_full(conn, wallet_id)
        feats = compute_features(rows, wallet_id, cfg)
        if feats is None:
            stats.skipped_no_tx += 1
            continue
        db.upsert_wallet_features(conn, wallet_id, feats)
        stats.processed += 1
        if i % 500 == 0:
            conn.commit()
            log.info("  обработано %d / %d", i, total)

    conn.commit()
    return stats
