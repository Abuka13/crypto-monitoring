"""Конфигурация из .env (секреты не хардкодятся)."""
from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


class ConfigError(RuntimeError):
    """Нет обязательной переменной окружения."""


def _required(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise ConfigError(f"Не задана переменная {name} (см. .env.example).")
    return value


ETH = 10 ** 18  # 1 ETH в wei


@dataclass(frozen=True)
class RiskConfig:
    """Пороги Rule Engine (wei как int). Меняются через .env без правки кода."""

    large_amount_threshold_wei: int          # «Большая сумма»
    new_wallet_max_age_days: int             # «Новый кошелёк»: возраст
    high_frequency_count: int                # «Высокая частота»: N транзакций
    high_frequency_window_hours: int         #   в окне M часов
    structuring_small_amount_wei: int        # «Дробление»: порог мелкой суммы
    structuring_min_count: int               #   и минимум таких операций

    @staticmethod
    def load() -> "RiskConfig":
        return RiskConfig(
            large_amount_threshold_wei=int(
                os.getenv("RISK_LARGE_AMOUNT_WEI", str(10 * ETH))
            ),
            new_wallet_max_age_days=int(os.getenv("RISK_NEW_WALLET_MAX_AGE_DAYS", "30")),
            high_frequency_count=int(os.getenv("RISK_HIGH_FREQ_COUNT", "50")),
            high_frequency_window_hours=int(os.getenv("RISK_HIGH_FREQ_WINDOW_HOURS", "24")),
            structuring_small_amount_wei=int(
                os.getenv("RISK_STRUCTURING_SMALL_WEI", str(ETH // 100))
            ),
            structuring_min_count=int(os.getenv("RISK_STRUCTURING_MIN_COUNT", "30")),
        )


@dataclass(frozen=True)
class Config:
    database_url: str
    etherscan_api_key: str
    etherscan_base_url: str        # V2 multichain-эндпоинт
    etherscan_chain_id: int
    requests_per_second: float     # лимит бесплатного ключа ~5/с
    risk: RiskConfig

    @staticmethod
    def load() -> "Config":
        return Config(
            database_url=_required("DATABASE_URL"),
            etherscan_api_key=_required("ETHERSCAN_API_KEY"),
            etherscan_base_url=os.getenv(
                "ETHERSCAN_BASE_URL", "https://api.etherscan.io/v2/api"
            ),
            etherscan_chain_id=int(os.getenv("ETHERSCAN_CHAIN_ID", "1")),
            requests_per_second=float(os.getenv("ETHERSCAN_RPS", "4")),
            risk=RiskConfig.load(),
        )
