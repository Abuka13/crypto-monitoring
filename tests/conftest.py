"""Общие фикстуры тестов.

Две вещи, которые здесь важны:

1. Наши таблицы описаны вручную в db/schema.sql и подключены к Django как
   managed=False, поэтому обычные миграции их не создают — схему накатываем сами
   поверх тестовой базы, которую поднял pytest-django.
2. Сеть в тестах запрещена целиком (autouse-фикстура): ни один тест не должен
   ходить в Etherscan, к LLM-провайдеру или куда-либо ещё. Попытка — сразу
   падение с понятным сообщением, а не тихий запрос наружу.
"""
from __future__ import annotations

import socket
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest
from django.db import connection

BASE_DIR = Path(__file__).resolve().parent.parent
SCHEMA = BASE_DIR / "db" / "schema.sql"


# --------------------------------------------------------------------------
# Схема тестовой базы
# --------------------------------------------------------------------------
@pytest.fixture(scope="session")
def django_db_setup(django_db_setup, django_db_blocker):
    """После стандартной подготовки БД накатываем db/schema.sql.

    Так тесты проверяют ровно ту схему, которая едет в продакшн, включая
    CHECK-ограничения, уникальные индексы и стартовые справочники.
    """
    with django_db_blocker.unblock():
        with connection.cursor() as cur:
            cur.execute(SCHEMA.read_text(encoding="utf-8"))


# --------------------------------------------------------------------------
# Запрет сети
# --------------------------------------------------------------------------
class NetworkAccessDenied(RuntimeError):
    """Тест попытался выйти в сеть — так быть не должно."""


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """Блокируем исходящие соединения, кроме локальной БД."""
    real_connect = socket.socket.connect

    def guard(self, address, *args, **kwargs):
        host = address[0] if isinstance(address, tuple) else address
        if host in ("127.0.0.1", "::1", "localhost"):
            return real_connect(self, address, *args, **kwargs)
        raise NetworkAccessDenied(
            f"Тест попытался обратиться к {host}. Внешние вызовы должны быть замоканы."
        )

    monkeypatch.setattr(socket.socket, "connect", guard)


# --------------------------------------------------------------------------
# Данные
# --------------------------------------------------------------------------
@pytest.fixture
def api_client(db):
    """DRF-клиент с аутентифицированным пользователем."""
    from django.contrib.auth.models import User
    from rest_framework.test import APIClient

    user = User.objects.create_user(username="analyst", password="x")
    client = APIClient()
    client.force_authenticate(user=user)
    return client


@pytest.fixture
def anon_client(db):
    from rest_framework.test import APIClient
    return APIClient()


@pytest.fixture
def network_id(db) -> int:
    """id сети Ethereum из стартовых данных schema.sql."""
    with connection.cursor() as cur:
        cur.execute("SELECT id FROM blockchain_network WHERE name = 'Ethereum'")
        return cur.fetchone()[0]


@pytest.fixture
def make_wallet(db, network_id):
    """Фабрика кошельков. Адрес уникален в пределах сети."""
    counter = {"n": 0}

    def _make(address: str | None = None, *, label: str | None = None,
              label_source: str | None = None, first_seen: datetime | None = None,
              tx_count: int = 0) -> int:
        counter["n"] += 1
        address = address or f"0x{counter['n']:040x}"
        with connection.cursor() as cur:
            cur.execute(
                """
                INSERT INTO wallet (address, network_id, label, label_source,
                                    first_seen_at, last_seen_at, transaction_count)
                VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id
                """,
                [address.lower(), network_id, label, label_source,
                 first_seen, first_seen, tx_count],
            )
            return cur.fetchone()[0]

    return _make


@pytest.fixture
def make_tx(db, network_id):
    """Фабрика транзакций между кошельками (суммы — целые wei)."""
    counter = {"n": 0}

    def _make(sender_id: int, receiver_id: int, *, amount_wei: int = 10**18,
              when: datetime | None = None, block: int = 1_000_000) -> int:
        counter["n"] += 1
        when = when or datetime(2026, 1, 1, tzinfo=timezone.utc)
        with connection.cursor() as cur:
            cur.execute(
                """
                INSERT INTO tx (tx_hash, network_id, sender_wallet_id, receiver_wallet_id,
                                amount, currency, gas_fee, block_number,
                                transaction_timestamp, status)
                VALUES (%s, %s, %s, %s, %s, 'ETH', 0, %s, %s, 'success')
                RETURNING id
                """,
                [f"0x{counter['n']:064x}", network_id, sender_id, receiver_id,
                 Decimal(amount_wei), block, when],
            )
            return cur.fetchone()[0]

    return _make


@pytest.fixture
def risk_cfg():
    """Пороги Rule Engine с фиксированными значениями — тесты не зависят от .env."""
    from collector.config import RiskConfig

    return RiskConfig(
        large_amount_threshold_wei=10 * 10**18,
        new_wallet_max_age_days=30,
        high_frequency_count=50,
        high_frequency_window_hours=24,
        structuring_small_amount_wei=10**16,
        structuring_min_count=30,
        weight_rule=0.6,
        weight_ml=0.4,
        ml_exclude_labels=frozenset({"contract", "exchange"}),
    )


@pytest.fixture
def decision_cfg():
    """Пороги Decision Engine, зафиксированные в тесте (не берутся из .env)."""
    from collector.config import DecisionConfig

    return DecisionConfig(
        rule_critical=75.0,
        rule_high=50.0,
        rule_medium=25.0,
        ml_high=70.0,
        graph_high=70.0,
        strong_rules=frozenset({"Связь с миксером"}),
        hard_signal_labels=frozenset({"sanctioned", "blacklist", "fraud"}),
        trusted_labels=frozenset({"exchange", "contract"}),
    )


@pytest.fixture
def llm_cfg():
    """Настроенный (фиктивно) LLM-провайдер — живых вызовов в тестах нет."""
    from collector.config import LLMConfig

    return LLMConfig(
        provider="anthropic", model="test-model", api_key="test-key",
        base_url=None, max_tokens=1000, timeout_seconds=5.0, effort="low",
    )


@pytest.fixture
def hours_ago():
    """Момент N часов назад — для правил, зависящих от времени."""
    def _at(hours: float) -> datetime:
        return datetime.now(timezone.utc) - timedelta(hours=hours)
    return _at
