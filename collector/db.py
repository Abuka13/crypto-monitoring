"""Доступ к PostgreSQL (raw psycopg2). wei — Python int -> NUMERIC, без float."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

import psycopg2
import psycopg2.extensions


def connect(database_url: str) -> psycopg2.extensions.connection:
    return psycopg2.connect(database_url)


def get_network_id(conn, name: str) -> int:
    """id сети из blockchain_network по имени."""
    with conn.cursor() as cur:
        cur.execute("SELECT id FROM blockchain_network WHERE name = %s", (name,))
        row = cur.fetchone()
    if row is None:
        raise ValueError(f"Сеть '{name}' не найдена — примени db/schema.sql.")
    return row[0]


def find_or_create_wallet(
    conn, network_id: int, address: str, seen_at: datetime
) -> int:
    """id кошелька, создавая при первом появлении (адрес в нижнем регистре)."""
    address = address.lower()
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id FROM wallet WHERE network_id = %s AND address = %s",
            (network_id, address),
        )
        row = cur.fetchone()
        if row is not None:
            return row[0]

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

        # Гонка: вставили между SELECT и INSERT — перечитываем.
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
    """Вставить транзакцию. None если дубль (не трогать агрегаты при повторе)."""
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
    """Агрегаты кошельков: +sent/+received, +1 count, last_seen. self-tx — отдельно."""
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


# ---- Rule Engine: правила, оценки риска, алерты ----

@dataclass(frozen=True)
class Rule:
    id: int
    name: str
    description: str | None
    score: Decimal


def get_active_rules(conn) -> list[Rule]:
    """Включённые правила (is_active = TRUE)."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, name, description, score FROM rule "
            "WHERE is_active = TRUE ORDER BY id"
        )
        return [Rule(r[0], r[1], r[2], r[3]) for r in cur.fetchall()]


def get_transactions_for_scoring(conn) -> list[tuple]:
    """Все tx с метками кошельков: (tx_id, amount, sender_label, receiver_label)."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT t.id, t.amount, sw.label, rw.label
            FROM tx t
            JOIN wallet sw ON sw.id = t.sender_wallet_id
            JOIN wallet rw ON rw.id = t.receiver_wallet_id
            ORDER BY t.id
            """
        )
        return cur.fetchall()


def get_wallets_for_scoring(conn) -> list[tuple]:
    """Все кошельки: (id, address, first_seen_at, label)."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, address, first_seen_at, label FROM wallet ORDER BY id"
        )
        return cur.fetchall()


# ---- Инкрементальный расчёт: выборки по одному блоку ----

def get_transactions_for_scoring_by_block(conn, network_id: int, block_number: int) -> list[tuple]:
    """tx одного блока: (id, amount, sender_label, receiver_label)."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT t.id, t.amount, sw.label, rw.label
            FROM tx t
            JOIN wallet sw ON sw.id = t.sender_wallet_id
            JOIN wallet rw ON rw.id = t.receiver_wallet_id
            WHERE t.network_id = %s AND t.block_number = %s
            ORDER BY t.id
            """,
            (network_id, block_number),
        )
        return cur.fetchall()


def get_affected_wallet_ids_by_block(conn, network_id: int, block_number: int) -> list[int]:
    """id кошельков — участников блока."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT sender_wallet_id FROM tx WHERE network_id = %s AND block_number = %s
            UNION
            SELECT receiver_wallet_id FROM tx WHERE network_id = %s AND block_number = %s
            """,
            (network_id, block_number, network_id, block_number),
        )
        return [row[0] for row in cur.fetchall()]


def get_wallets_for_scoring_by_ids(conn, wallet_ids: list[int]) -> list[tuple]:
    """Кошельки по списку id: (id, address, first_seen_at, label)."""
    if not wallet_ids:
        return []
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, address, first_seen_at, label FROM wallet WHERE id = ANY(%s) ORDER BY id",
            (list(wallet_ids),),
        )
        return cur.fetchall()


def get_wallet_tx_history(conn, wallet_id: int) -> list[tuple]:
    """(timestamp, amount) всех транзакций кошелька."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT transaction_timestamp, amount
            FROM tx
            WHERE sender_wallet_id = %s OR receiver_wallet_id = %s
            ORDER BY transaction_timestamp
            """,
            (wallet_id, wallet_id),
        )
        return cur.fetchall()


def insert_transaction_risk(
    conn, *, transaction_id: int, rule_score: Decimal,
    ml_score: Decimal, final_score: Decimal, risk_level: str,
) -> int:
    """Новая оценка риска транзакции (история)."""
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO transaction_risk
                (transaction_id, rule_score, ml_score, final_score, risk_level)
            VALUES (%s, %s, %s, %s, %s)
            RETURNING id
            """,
            (transaction_id, rule_score, ml_score, final_score, risk_level),
        )
        return cur.fetchone()[0]


def insert_wallet_risk(
    conn, *, wallet_id: int, rule_score: Decimal,
    ml_score: Decimal, final_score: Decimal, risk_level: str,
) -> int:
    """Новая оценка риска кошелька (история)."""
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO wallet_risk
                (wallet_id, rule_score, ml_score, final_score, risk_level)
            VALUES (%s, %s, %s, %s, %s)
            RETURNING id
            """,
            (wallet_id, rule_score, ml_score, final_score, risk_level),
        )
        return cur.fetchone()[0]


def update_wallet_risk_summary(
    conn, *, wallet_id: int, risk_score: Decimal, is_flagged: bool
) -> None:
    """Снимок риска кошелька (risk_score, is_flagged)."""
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE wallet SET risk_score = %s, is_flagged = %s, updated_at = now() "
            "WHERE id = %s",
            (risk_score, is_flagged, wallet_id),
        )


def insert_alert(
    conn, *, target_type: str, title: str, description: str, level: str,
    transaction_risk_id: int | None = None, wallet_risk_id: int | None = None,
) -> int:
    """Создать алерт (ровно один источник риска — гарантирует CHECK)."""
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO alert
                (transaction_risk_id, wallet_risk_id, target_type,
                 title, description, level, status)
            VALUES (%s, %s, %s, %s, %s, %s, 'open')
            RETURNING id
            """,
            (transaction_risk_id, wallet_risk_id, target_type,
             title, description, level),
        )
        return cur.fetchone()[0]


# Очищаемые таблицы (справочники blockchain_network и rule не входят).
_DATA_TABLES = ("alert", "transaction_risk", "wallet_risk", "tx", "wallet")


def count_data_tables(conn) -> dict[str, int]:
    """Число строк в очищаемых таблицах (предпросмотр)."""
    counts: dict[str, int] = {}
    with conn.cursor() as cur:
        for table in _DATA_TABLES:
            cur.execute(f"SELECT count(*) FROM {table}")
            counts[table] = cur.fetchone()[0]
    return counts


def reset_data(conn) -> dict[str, int]:
    """TRUNCATE данных (справочники сохраняются). Возвращает счётчики удалённого."""
    deleted = count_data_tables(conn)
    with conn.cursor() as cur:
        cur.execute(
            "TRUNCATE TABLE alert, transaction_risk, wallet_risk, tx, wallet "
            "RESTART IDENTITY CASCADE"
        )
    conn.commit()
    return deleted


# ---- Метки адресов ----

def upsert_wallet_label(
    conn, network_id: int, address: str, label: str, source: str
) -> str:
    """Проставить метку адресу; кошелёк создаётся, если его ещё нет.

    Идемпотентно. Возвращает 'created' | 'updated' | 'unchanged'.
    """
    address = address.lower()
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, label, label_source FROM wallet WHERE network_id = %s AND address = %s",
            (network_id, address),
        )
        row = cur.fetchone()
        if row is None:
            cur.execute(
                """
                INSERT INTO wallet (address, network_id, label, label_source, labeled_at)
                VALUES (%s, %s, %s, %s, now())
                ON CONFLICT (network_id, address) DO UPDATE
                    SET label = EXCLUDED.label, label_source = EXCLUDED.label_source,
                        labeled_at = now(), updated_at = now()
                """,
                (address, network_id, label, source),
            )
            return "created"
        if row[1] == label and row[2] == source:
            return "unchanged"
        cur.execute(
            "UPDATE wallet SET label=%s, label_source=%s, labeled_at=now(), updated_at=now() "
            "WHERE id=%s",
            (label, source, row[0]),
        )
        return "updated"


# ---- Дедуп алертов: один активный (open/in_progress) на объект ----

def find_active_alert_for_wallet(conn, wallet_id: int) -> int | None:
    """id активного алерта по кошельку, иначе None."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT a.id FROM alert a
            JOIN wallet_risk wr ON wr.id = a.wallet_risk_id
            WHERE a.status IN ('open', 'in_progress') AND wr.wallet_id = %s
            ORDER BY a.id DESC LIMIT 1
            """,
            (wallet_id,),
        )
        row = cur.fetchone()
        return row[0] if row else None


def find_active_alert_for_transaction(conn, transaction_id: int) -> int | None:
    """id активного алерта по транзакции, иначе None."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT a.id FROM alert a
            JOIN transaction_risk tr ON tr.id = a.transaction_risk_id
            WHERE a.status IN ('open', 'in_progress') AND tr.transaction_id = %s
            ORDER BY a.id DESC LIMIT 1
            """,
            (transaction_id,),
        )
        row = cur.fetchone()
        return row[0] if row else None


def refresh_alert(
    conn, *, alert_id: int, target_type: str, risk_id: int,
    title: str, description: str, level: str,
) -> None:
    """Обновить активный алерт свежей оценкой (статус не трогаем)."""
    with conn.cursor() as cur:
        if target_type == "wallet":
            cur.execute(
                "UPDATE alert SET wallet_risk_id=%s, transaction_risk_id=NULL, "
                "title=%s, description=%s, level=%s, created_at=now() WHERE id=%s",
                (risk_id, title, description, level, alert_id),
            )
        else:
            cur.execute(
                "UPDATE alert SET transaction_risk_id=%s, wallet_risk_id=NULL, "
                "title=%s, description=%s, level=%s, created_at=now() WHERE id=%s",
                (risk_id, title, description, level, alert_id),
            )


def get_sample_alerts(conn, limit: int = 5) -> list[tuple]:
    """Свежие алерты для отчёта в CLI."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT target_type, level, status, title, description, created_at
            FROM alert
            ORDER BY created_at DESC, id DESC
            LIMIT %s
            """,
            (limit,),
        )
        return cur.fetchall()
