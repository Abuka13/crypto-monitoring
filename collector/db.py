"""Доступ к PostgreSQL: подключение и репозиторий кошельков/транзакций.

Денежные суммы (wei) передаются как Python int и ложатся в NUMERIC(40,0)
без потери точности — никаких float.
"""
from __future__ import annotations

from datetime import datetime

import psycopg2
import psycopg2.extensions


def connect(database_url: str) -> psycopg2.extensions.connection:
    """Открыть подключение к БД по строке вида postgresql://user:pass@host/db."""
    return psycopg2.connect(database_url)


def get_network_id(conn, name: str) -> int:
    """id сети из blockchain_network по имени (например, 'Ethereum')."""
    with conn.cursor() as cur:
        cur.execute("SELECT id FROM blockchain_network WHERE name = %s", (name,))
        row = cur.fetchone()
    if row is None:
        raise ValueError(
            f"Сеть '{name}' не найдена в blockchain_network. "
            f"Сначала примени db/schema.sql (там есть стартовые данные)."
        )
    return row[0]


def find_or_create_wallet(
    conn, network_id: int, address: str, seen_at: datetime
) -> int:
    """Вернуть id кошелька, создав запись при первом появлении адреса.

    Кошельки обязаны существовать ДО вставки транзакции из-за внешних ключей
    sender_wallet_id / receiver_wallet_id. Адрес приводим к нижнему регистру,
    чтобы один и тот же кошелёк не задвоился из-за разного регистра hex.
    """
    address = address.lower()
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id FROM wallet WHERE network_id = %s AND address = %s",
            (network_id, address),
        )
        row = cur.fetchone()
        if row is not None:
            return row[0]

        # Записи нет — создаём. ON CONFLICT защищает от гонки при параллельном сборе.
        cur.execute(
            """
            INSERT INTO wallet (address, network_id, first_seen_at, last_seen_at)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (network_id, address) DO NOTHING
            RETURNING id
            """,
            (address, network_id, seen_at, seen_at),
        )
        row = cur.fetchone()
        if row is not None:
            return row[0]

        # Кто-то успел вставить между SELECT и INSERT — перечитываем.
        cur.execute(
            "SELECT id FROM wallet WHERE network_id = %s AND address = %s",
            (network_id, address),
        )
        return cur.fetchone()[0]


def insert_transaction(
    conn,
    *,
    network_id: int,
    tx_hash: str,
    sender_wallet_id: int,
    receiver_wallet_id: int,
    amount_wei: int,
    gas_fee_wei: int,
    block_number: int,
    timestamp: datetime,
    status: str,
    currency: str = "ETH",
) -> int | None:
    """Вставить транзакцию в tx.

    Возвращает id новой строки, либо None, если такая транзакция уже была
    (уникальность по network_id + tx_hash). None — сигнал не трогать агрегаты,
    чтобы повторный запуск сбора не задваивал суммы.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO tx (
                tx_hash, network_id, sender_wallet_id, receiver_wallet_id,
                amount, currency, gas_fee, block_number,
                transaction_timestamp, status
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (network_id, tx_hash) DO NOTHING
            RETURNING id
            """,
            (
                tx_hash, network_id, sender_wallet_id, receiver_wallet_id,
                amount_wei, currency, gas_fee_wei, block_number,
                timestamp, status,
            ),
        )
        row = cur.fetchone()
        return row[0] if row else None


def update_wallet_aggregates(
    conn,
    *,
    sender_wallet_id: int,
    receiver_wallet_id: int,
    amount_wei: int,
    timestamp: datetime,
) -> None:
    """Обновить агрегаты обоих кошельков после новой транзакции.

    Отправитель: +amount к total_sent. Получатель: +amount к total_received.
    Обоим: +1 к transaction_count и last_seen_at = max(last_seen_at, ts).
    Случай sender == receiver (перевод самому себе) учитывается отдельно,
    чтобы не посчитать транзакцию дважды.
    """
    with conn.cursor() as cur:
        if sender_wallet_id == receiver_wallet_id:
            cur.execute(
                """
                UPDATE wallet
                   SET total_sent        = total_sent + %s,
                       total_received    = total_received + %s,
                       transaction_count = transaction_count + 1,
                       last_seen_at      = GREATEST(COALESCE(last_seen_at, %s), %s),
                       updated_at        = now()
                 WHERE id = %s
                """,
                (amount_wei, amount_wei, timestamp, timestamp, sender_wallet_id),
            )
            return

        cur.execute(
            """
            UPDATE wallet
               SET total_sent        = total_sent + %s,
                   transaction_count = transaction_count + 1,
                   last_seen_at      = GREATEST(COALESCE(last_seen_at, %s), %s),
                   updated_at        = now()
             WHERE id = %s
            """,
            (amount_wei, timestamp, timestamp, sender_wallet_id),
        )
        cur.execute(
            """
            UPDATE wallet
               SET total_received    = total_received + %s,
                   transaction_count = transaction_count + 1,
                   last_seen_at      = GREATEST(COALESCE(last_seen_at, %s), %s),
                   updated_at        = now()
             WHERE id = %s
            """,
            (amount_wei, timestamp, timestamp, receiver_wallet_id),
        )
