"""Приём транзакций в БД: кошельки -> tx -> агрегаты (каждая в своей DB-транзакции)."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Iterable

from . import db
from .sources.base import BlockchainSource, RawTransaction

log = logging.getLogger(__name__)


@dataclass
class IngestStats:
    seen: int = 0       # всего пришло из источника
    inserted: int = 0   # реально вставлено новых
    skipped: int = 0    # уже были в БД (дубликаты)
    failed: int = 0     # ошибки при обработке

    def __str__(self) -> str:
        return (
            f"получено={self.seen}, вставлено={self.inserted}, "
            f"пропущено(дубликаты)={self.skipped}, ошибок={self.failed}"
        )


def ingest_transactions(
    conn,
    network_id: int,
    transactions: Iterable[RawTransaction],
) -> IngestStats:
    stats = IngestStats()

    for tx in transactions:
        stats.seen += 1
        try:
            # 1) кошельки — до вставки tx (внешние ключи)
            sender_id = db.find_or_create_wallet(
                conn, network_id, tx.sender_address, tx.timestamp
            )
            receiver_id = db.find_or_create_wallet(
                conn, network_id, tx.receiver_address, tx.timestamp
            )

            # 2) транзакция
            tx_id = db.insert_transaction(
                conn,
                network_id=network_id,
                tx_hash=tx.tx_hash,
                sender_wallet_id=sender_id,
                receiver_wallet_id=receiver_id,
                amount_wei=tx.amount_wei,
                gas_fee_wei=tx.gas_fee_wei,
                block_number=tx.block_number,
                timestamp=tx.timestamp,
                status=tx.status,
                currency=tx.currency,
            )

            if tx_id is None:
                conn.commit()  # дубль: агрегаты не трогаем
                stats.skipped += 1
                continue

            # 3) агрегаты — только для новой транзакции
            db.update_wallet_aggregates(
                conn,
                sender_wallet_id=sender_id,
                receiver_wallet_id=receiver_id,
                amount_wei=tx.amount_wei,
                timestamp=tx.timestamp,
            )
            conn.commit()
            stats.inserted += 1

        except Exception as exc:  # одна плохая транзакция не валит весь сбор
            conn.rollback()
            stats.failed += 1
            log.error("Не удалось обработать транзакцию %s: %s", tx.tx_hash, exc)

    return stats


def collect_by_address(
    conn,
    source: BlockchainSource,
    network_id: int,
    address: str,
    max_transactions: int | None = None,
) -> IngestStats:
    """Собрать и сохранить транзакции одного адреса."""
    txs = source.get_transactions_by_address(
        address, max_transactions=max_transactions
    )
    return ingest_transactions(conn, network_id, txs)


def collect_by_block(
    conn,
    source: BlockchainSource,
    network_id: int,
    block_number: int,
) -> IngestStats:
    """Собрать и сохранить все транзакции одного блока."""
    txs = source.get_transactions_by_block(block_number)
    return ingest_transactions(conn, network_id, txs)
