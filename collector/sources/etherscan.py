"""Адаптер к Etherscan API.

Единственное место, где код знает о формате Etherscan. Наружу отдаёт
нормализованные RawTransaction (см. base.py). Здесь же — учёт лимита
бесплатного ключа (~5 req/s) и устойчивость к сетевым ошибкам.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Any, Iterator

import requests

from .base import BlockchainSource, RawTransaction

log = logging.getLogger(__name__)

# Адрес контракт-создания / "сожжённых" переводов, когда поле `to` пустое.
_ZERO_ADDRESS = "0x0000000000000000000000000000000000000000"


class EtherscanError(RuntimeError):
    """Etherscan вернул логическую ошибку (не сетевую)."""


class _RateLimiter:
    """Простой ограничитель: не чаще N запросов в секунду.

    Засыпает ровно настолько, чтобы выдержать минимальный интервал между
    обращениями. Бесплатный ключ Etherscan = ~5 req/s, держим с запасом.
    """

    def __init__(self, requests_per_second: float) -> None:
        self._min_interval = 1.0 / requests_per_second if requests_per_second > 0 else 0.0
        self._last_call = 0.0

    def wait(self) -> None:
        elapsed = time.monotonic() - self._last_call
        sleep_for = self._min_interval - elapsed
        if sleep_for > 0:
            time.sleep(sleep_for)
        self._last_call = time.monotonic()


class EtherscanSource(BlockchainSource):
    network_name = "Ethereum"

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.etherscan.io/v2/api",
        chain_id: int = 1,
        requests_per_second: float = 4.0,
        page_size: int = 1000,
        max_retries: int = 5,
        timeout: float = 30.0,
    ) -> None:
        self._api_key = api_key
        self._base_url = base_url
        self._chain_id = chain_id
        self._page_size = page_size
        self._max_retries = max_retries
        self._timeout = timeout
        self._limiter = _RateLimiter(requests_per_second)
        self._session = requests.Session()

    # ------------------------------------------------------------------
    # Низкоуровневый запрос: rate limit + повторы при сбоях
    # ------------------------------------------------------------------
    def _request(self, params: dict[str, Any]) -> Any:
        params = {**params, "chainid": self._chain_id, "apikey": self._api_key}

        last_error: Exception | None = None
        for attempt in range(1, self._max_retries + 1):
            self._limiter.wait()
            try:
                resp = self._session.get(
                    self._base_url, params=params, timeout=self._timeout
                )
                # 429 / 5xx — временные, имеет смысл повторить.
                if resp.status_code == 429 or resp.status_code >= 500:
                    raise requests.HTTPError(f"HTTP {resp.status_code}")
                resp.raise_for_status()
                data = resp.json()
            except (requests.RequestException, ValueError) as exc:
                last_error = exc
                backoff = min(2 ** attempt, 30)
                log.warning(
                    "Сетевая ошибка (%s), попытка %d/%d, пауза %ds",
                    exc, attempt, self._max_retries, backoff,
                )
                time.sleep(backoff)
                continue

            message = str(data.get("message", ""))
            result = data.get("result")

            # Превышение лимита может прийти в любом формате — обрабатываем первым.
            if "rate limit" in str(result).lower() or "rate limit" in message.lower():
                backoff = min(2 ** attempt, 30)
                log.warning("Лимит Etherscan, пауза %ds (попытка %d/%d)",
                            backoff, attempt, self._max_retries)
                time.sleep(backoff)
                last_error = EtherscanError(str(result) or message)
                continue

            # Модуль proxy отвечает в формате JSON-RPC (нет поля status).
            if "jsonrpc" in data:
                if data.get("error"):
                    raise EtherscanError(f"Etherscan proxy: {data['error']}")
                return result

            # Обычные модули (account и т.п.) используют поле status.
            status = str(data.get("status"))
            if status == "1":
                return result
            # status == "0": либо "нет данных" (норма), либо ошибка.
            if "No transactions found" in message or result == []:
                return []
            # Прочая логическая ошибка — повторять смысла нет.
            raise EtherscanError(f"Etherscan: {message} / {result}")

        raise EtherscanError(
            f"Не удалось получить данные после {self._max_retries} попыток: {last_error}"
        )

    # ------------------------------------------------------------------
    # Нормализация формата Etherscan -> RawTransaction
    # ------------------------------------------------------------------
    @staticmethod
    def _to_raw(item: dict[str, Any]) -> RawTransaction:
        gas_used = int(item.get("gasUsed", 0) or 0)
        gas_price = int(item.get("gasPrice", 0) or 0)
        # Для контракт-создания поле `to` пустое — берём адрес контракта.
        receiver = item.get("to") or item.get("contractAddress") or _ZERO_ADDRESS
        # isError == "1" => транзакция завершилась с ошибкой.
        status = "failed" if str(item.get("isError", "0")) == "1" else "success"
        return RawTransaction(
            tx_hash=item["hash"],
            sender_address=item["from"],
            receiver_address=receiver,
            amount_wei=int(item.get("value", 0) or 0),
            gas_fee_wei=gas_used * gas_price,
            block_number=int(item["blockNumber"]),
            timestamp=datetime.fromtimestamp(int(item["timeStamp"]), tz=timezone.utc),
            status=status,
        )

    # ------------------------------------------------------------------
    # Публичные методы интерфейса
    # ------------------------------------------------------------------
    def get_transactions_by_address(
        self,
        address: str,
        start_block: int = 0,
        end_block: int = 99_999_999,
        max_transactions: int | None = None,
    ) -> Iterator[RawTransaction]:
        page = 1
        yielded = 0
        while True:
            result = self._request(
                {
                    "module": "account",
                    "action": "txlist",
                    "address": address,
                    "startblock": start_block,
                    "endblock": end_block,
                    "page": page,
                    "offset": self._page_size,
                    "sort": "desc",
                }
            )
            if not result:
                return
            for item in result:
                yield self._to_raw(item)
                yielded += 1
                if max_transactions is not None and yielded >= max_transactions:
                    return
            # Последняя страница, если вернулось меньше, чем размер страницы.
            if len(result) < self._page_size:
                return
            page += 1

    def get_latest_block_number(self) -> int:
        # proxy eth_blockNumber возвращает номер вершины цепочки (hex-строка).
        result = self._request({"module": "proxy", "action": "eth_blockNumber"})
        return int(result, 16)

    def get_transactions_by_block(self, block_number: int) -> Iterator[RawTransaction]:
        # proxy-модуль отдаёт сырой блок Ethereum (формат eth_getBlockByNumber).
        result = self._request(
            {
                "module": "proxy",
                "action": "eth_getBlockByNumber",
                "tag": hex(block_number),
                "boolean": "true",
            }
        )
        if not result:
            return
        block_ts = datetime.fromtimestamp(int(result["timestamp"], 16), tz=timezone.utc)
        for item in result.get("transactions", []):
            receiver = item.get("to") or _ZERO_ADDRESS
            yield RawTransaction(
                tx_hash=item["hash"],
                sender_address=item["from"],
                receiver_address=receiver,
                amount_wei=int(item["value"], 16),
                # В сыром блоке нет gasUsed (нужен receipt) — комиссию здесь не считаем.
                gas_fee_wei=0,
                block_number=int(item["blockNumber"], 16),
                timestamp=block_ts,
                status="success",
            )
