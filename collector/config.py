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


@dataclass(frozen=True)
class Config:
    database_url: str
    etherscan_api_key: str
    # Etherscan перешёл на единый multichain-эндпоинт V2 (chainid выбирает сеть).
    etherscan_base_url: str
    etherscan_chain_id: int
    # Лимит бесплатного ключа — ~5 запросов в секунду. Берём с запасом.
    requests_per_second: float

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
        )
