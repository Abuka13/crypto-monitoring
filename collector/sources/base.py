"""Абстракция источника данных блокчейна.

Остальной код (ingest, db) работает ТОЛЬКО с этим интерфейсом и с
нормализованной моделью RawTransaction. Конкретный источник (Etherscan,
свой RPC-узел, другой провайдер) — деталь реализации: чтобы заменить
Etherscan, достаточно написать новый класс-наследник BlockchainSource,
не трогая ingest/db.
"""
from __future__ import annotations

import abc
from dataclasses import dataclass
from datetime import datetime
from typing import Iterator


@dataclass(frozen=True)
class RawTransaction:
    """Транзакция блокчейна в виде, не зависящем от конкретного провайдера.

    Все денежные величины — в наименьших единицах сети (для Ethereum это
    wei) и хранятся как int, чтобы не терять точность при работе с NUMERIC.
    """

    tx_hash: str
    sender_address: str
    receiver_address: str
    amount_wei: int            # сумма перевода, wei
    gas_fee_wei: int           # фактическая комиссия (gasUsed * gasPrice), wei
    block_number: int
    timestamp: datetime        # время операции (timezone-aware, UTC)
    status: str                # 'success' / 'failed'
    currency: str = "ETH"


class BlockchainSource(abc.ABC):
    """Интерфейс источника транзакций.

    Реализации обязаны возвращать уже нормализованные RawTransaction.
    """

    #: Имя сети в таблице blockchain_network (например, 'Ethereum').
    network_name: str = "Ethereum"

    @abc.abstractmethod
    def get_transactions_by_address(
        self,
        address: str,
        start_block: int = 0,
        end_block: int = 99_999_999,
        max_transactions: int | None = None,
    ) -> Iterator[RawTransaction]:
        """Транзакции, в которых участвовал адрес (как отправитель/получатель)."""

    @abc.abstractmethod
    def get_transactions_by_block(self, block_number: int) -> Iterator[RawTransaction]:
        """Все транзакции одного блока."""

    @abc.abstractmethod
    def get_latest_block_number(self) -> int:
        """Номер самого свежего (последнего) блока сети — вершина цепочки."""
