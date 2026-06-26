"""Загрузка конфигурации из .env.

Секреты (API-ключ, строка подключения к БД) НЕ хардкодятся в коде —
берутся из переменных окружения. Шаблон значений — в .env.example.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

# Подхватываем .env из корня проекта (если он есть).
load_dotenv()


class ConfigError(RuntimeError):
    """Не хватает обязательной переменной окружения."""


def _required(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise ConfigError(
            f"Не задана переменная окружения {name}. "
            f"Скопируй .env.example в .env и впиши значение."
        )
    return value


# 1 ETH = 10^18 wei — базовая единица для порогов сумм.
ETH = 10 ** 18


@dataclass(frozen=True)
class RiskConfig:
    """Пороги Rule Engine. Все суммы — в wei (int), без float.

    Вынесены в конфиг/.env, чтобы менять чувствительность правил без правки кода
    (сами правила-условия живут в risk/rules.py).
    """

    # «Большая сумма»: боевой порог (по умолчанию 10 ETH).
    large_amount_threshold_wei: int
    # «Большая сумма (тест)»: низкий порог для демо — заведомо срабатывает
    # на части собранных транзакций, чтобы показать конвейер риск → алерт.
    large_amount_test_threshold_wei: int

    # «Новый кошелёк»: создан не давнее N дней и при этом крупный оборот.
    new_wallet_max_age_days: int

    # «Высокая частота»: >= N транзакций в окне из M часов.
    high_frequency_count: int
    high_frequency_window_hours: int

    # «Дробление сумм»: >= N операций не крупнее порога (structuring).
    structuring_small_amount_wei: int
    structuring_min_count: int

    @staticmethod
    def load() -> "RiskConfig":
        return RiskConfig(
            large_amount_threshold_wei=int(
                os.getenv("RISK_LARGE_AMOUNT_WEI", str(10 * ETH))
            ),
            large_amount_test_threshold_wei=int(
                os.getenv("RISK_LARGE_AMOUNT_TEST_WEI", str(ETH // 10_000))  # 0.0001 ETH
            ),
            new_wallet_max_age_days=int(os.getenv("RISK_NEW_WALLET_MAX_AGE_DAYS", "30")),
            high_frequency_count=int(os.getenv("RISK_HIGH_FREQ_COUNT", "10")),
            high_frequency_window_hours=int(os.getenv("RISK_HIGH_FREQ_WINDOW_HOURS", "24")),
            structuring_small_amount_wei=int(
                os.getenv("RISK_STRUCTURING_SMALL_WEI", str(ETH // 100))  # 0.01 ETH
            ),
            structuring_min_count=int(os.getenv("RISK_STRUCTURING_MIN_COUNT", "10")),
        )


@dataclass(frozen=True)
class Config:
    database_url: str
    etherscan_api_key: str
    # Etherscan перешёл на единый multichain-эндпоинт V2 (chainid выбирает сеть).
    etherscan_base_url: str
    etherscan_chain_id: int
    # Лимит бесплатного ключа — ~5 запросов в секунду. Берём с запасом.
    requests_per_second: float
    # Пороги Rule Engine.
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
