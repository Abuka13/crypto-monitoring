"""Адаптер к Etherscan API: rate limit, повторы, нормализация в RawTransaction."""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Any, Iterator

import requests

from .base import BlockchainSource, RawTransaction

log = logging.getLogger(__name__)

_ZERO_ADDRESS = "0x0000000000000000000000000000000000000000"  # когда `to` пустой


class EtherscanError(RuntimeError):
    """Логическая ошибка Etherscan (не сетевая)."""


class _RateLimiter:
    """Не чаще N запросов в секунду (лимит бесплатного ключа ~5/с)."""

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

    def _request(self, params: dict[str, Any]) -> Any:
        """Запрос с rate limit и повторами (429/5xx/сеть/лимит)."""
        params = {**params, "chainid": self._chain_id, "apikey": self._api_key}

        last_error: Exception | None = None
        for attempt in range(1, self._max_retries + 1):
            self._limiter.wait()
            try:
                resp = self._session.get(
                    self._base_url, params=params, timeout=self._timeout
                )
                if resp.status_code == 429 or resp.status_code >= 500:
                    raise requests.HTTPError(f"HTTP {resp.status_code}")
                resp.raise_for_status()
                data = resp.json()
            except (requests.RequestException, ValueError) as exc:
                last_error = exc
                backoff = min(2 ** attempt, 30)
                log.warning("Сетевая ошибка (%s), попытка %d/%d, пауза %ds",
                            exc, attempt, self._max_retries, backoff)
                time.sleep(backoff)
                continue

            message = str(data.get("message", ""))
            result = data.get("result")

            # Превышение лимита — в любом формате, обрабатываем первым.
            if "rate limit" in str(result).lower() or "rate limit" in message.lower():
                backoff = min(2 ** attempt, 30)
                log.warning("Лимит Etherscan, пауза %ds (попытка %d/%d)",
                            backoff, attempt, self._max_retries)
                time.sleep(backoff)
                last_error = EtherscanError(str(result) or message)
                continue

            # proxy отвечает в JSON-RPC (без поля status).
            if "jsonrpc" in data:
                if data.get("error"):
                    raise EtherscanError(f"Etherscan proxy: {data['error']}")
                return result

            # Обычные модули (account и т.п.) — по полю status.
            status = str(data.get("status"))
            if status == "1":
                return result
            if "No transactions found" in message or result == []:
                return []
            raise EtherscanError(f"Etherscan: {message} / {result}")

        raise EtherscanError(
            f"Не удалось получить данные после {self._max_retries} попыток: {last_error}"
        )

    @staticmethod
    def _to_raw(item: dict[str, Any]) -> RawTransaction:
        """Формат Etherscan (txlist) -> RawTransaction."""
        gas_used = int(item.get("gasUsed", 0) or 0)
        gas_price = int(item.get("gasPrice", 0) or 0)
        receiver = item.get("to") or item.get("contractAddress") or _ZERO_ADDRESS
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
            if len(result) < self._page_size:  # последняя страница
                return
            page += 1

    def get_latest_block_number(self) -> int:
        result = self._request({"module": "proxy", "action": "eth_blockNumber"})
        return int(result, 16)

    def is_contract(self, address: str) -> bool:
        """Смарт-контракт или обычный кошелёк (EOA).

        У контракта по адресу лежит байткод, у EOA код пустой ("0x") — это
        определение из самого протокола, а не эвристика.
        """
        result = self._request(
            {"module": "proxy", "action": "eth_getCode",
             "address": address, "tag": "latest"}
        )
        return bool(result) and str(result) not in ("0x", "0x0", "")

    def get_transactions_by_block(self, block_number: int) -> Iterator[RawTransaction]:
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
                gas_fee_wei=0,  # в сыром блоке нет gasUsed (нужен receipt)
                block_number=int(item["blockNumber"], 16),
                timestamp=block_ts,
                status="success",
            )
