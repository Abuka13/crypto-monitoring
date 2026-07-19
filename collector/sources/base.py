"""Абстракция источника данных блокчейна.

ingest/db работают только с этим интерфейсом и RawTransaction — чтобы заменить
Etherscan на свой RPC, достаточно нового наследника BlockchainSource.
"""
from __future__ import annotations

import abc
from dataclasses import dataclass
from datetime import datetime
from typing import Iterator


@dataclass(frozen=True)
class RawTransaction:
    """Транзакция в виде, не зависящем от провайдера (суммы — wei как int)."""

    tx_hash: str
    sender_address: str
    receiver_address: str
    amount_wei: int
    gas_fee_wei: int           # gasUsed * gasPrice
    block_number: int
    timestamp: datetime        # UTC, timezone-aware
    status: str                # 'success' / 'failed'
    currency: str = "ETH"


class BlockchainSource(abc.ABC):
    """Интерфейс источника транзакций (возвращает нормализованные RawTransaction)."""

    network_name: str = "Ethereum"  # имя сети в blockchain_network

    @abc.abstractmethod
    def get_transactions_by_address(
        self,
        address: str,
        start_block: int = 0,
        end_block: int = 99_999_999,
        max_transactions: int | None = None,
    ) -> Iterator[RawTransaction]:
        """Транзакции адреса (как отправителя/получателя)."""

    @abc.abstractmethod
    def get_transactions_by_block(self, block_number: int) -> Iterator[RawTransaction]:
        """Все транзакции одного блока."""

    @abc.abstractmethod
    def get_latest_block_number(self) -> int:
        """Номер последнего блока (вершина цепочки)."""
