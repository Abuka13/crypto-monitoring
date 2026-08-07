"""Определение смарт-контрактов (метка `contract`).

Зачем: популярные контракты (USDT, USDC, роутер Uniswap, инфраструктура OpenSea)
статистически экстремальны — десятки тысяч входящих вызовов от тысяч адресов — и
поэтому доминируют в топе аномалий ИИ. Но это структурно ДРУГОЙ тип объекта, а не
подозрительный кошелёк. Решение то же, что с биржами: метка + доверие.

Как определяем — два шага, чтобы не тратить лимит API впустую:

1. **Дешёвый отбор кандидатов (SQL).** Признак контракта в наших данных: адрес
   принимает вызовы, но сам никогда не инициирует транзакции (`tx_out = 0`), либо
   почти все операции по нему нулевые по сумме (`zero_tx_ratio` высокий — типичные
   вызовы методов контракта). Это лишь фильтр, не вывод.
2. **Подтверждение через `eth_getCode`.** У контракта по адресу лежит байткод, у
   обычного кошелька (EOA) код пустой. Это определение из самого протокола, а не
   догадка.

Почему нельзя ограничиться эвристикой: кошелёк-сборщик средств тоже «много
принимает и ничего не отправляет». Пометить его доверенным контрактом — значит
СПРЯТАТЬ настоящий риск, поэтому метка ставится только после проверки байткода.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from . import db

log = logging.getLogger(__name__)

LABEL_CONTRACT = "contract"
LABEL_SOURCE = "eth_getcode"   # источник метки: подтверждено байткодом


@dataclass
class ContractStats:
    candidates: int = 0
    checked: int = 0
    contracts: int = 0
    eoa: int = 0        # кандидаты, оказавшиеся обычными кошельками
    failed: int = 0

    def __str__(self) -> str:
        return (f"кандидатов={self.candidates}, проверено={self.checked}, "
                f"контрактов={self.contracts}, обычных кошельков={self.eoa}, "
                f"ошибок={self.failed}")


def detect_contracts(conn, source, network_id: int, *, min_tx: int = 5,
                     limit: int = 500) -> ContractStats:
    """Отобрать кандидатов и подтвердить контракты через eth_getCode.

    Идемпотентно: уже помеченные адреса повторно не проверяются (метка не
    меняется со временем — код по адресу не исчезает).
    """
    stats = ContractStats()
    candidates = db.get_contract_candidates(conn, min_tx=min_tx, limit=limit)
    stats.candidates = len(candidates)
    log.info("Кандидатов на контракт: %d (проверяем байткод через eth_getCode)", len(candidates))

    for i, (wallet_id, address) in enumerate(candidates, 1):
        try:
            is_contract = source.is_contract(address)
        except Exception as exc:  # сеть/лимит — пропускаем адрес, не роняем прогон
            stats.failed += 1
            log.warning("Не удалось проверить %s: %s", address, exc)
            continue

        stats.checked += 1
        if is_contract:
            db.upsert_wallet_label(conn, network_id, address, LABEL_CONTRACT, LABEL_SOURCE)
            stats.contracts += 1
        else:
            stats.eoa += 1

        if i % 25 == 0:
            conn.commit()
            log.info("  проверено %d / %d (контрактов: %d)", i, len(candidates), stats.contracts)

    conn.commit()
    return stats
