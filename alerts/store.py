"""Доступ к таблицам без Django-моделей (alert_explanation, address_screening).

Используется соединение Django, а не отдельное psycopg2-подключение к
DATABASE_URL: запрос и так выполняется внутри Django, поэтому лишнее соединение
только мешало бы — в частности, в тестах оно ходило бы мимо тестовой базы.
Стиль тот же, что в graph_query.py.
"""
from __future__ import annotations

from django.db import connection


def get_explanation(alert_id: int, lang: str, decision_hash: str) -> tuple | None:
    """Актуальное объяснение: (text, model, generated_at) или None.

    Ключ включает decision_hash — если решение по алерту изменилось, старое
    объяснение не подходит и будет сгенерировано заново.
    """
    with connection.cursor() as cur:
        cur.execute(
            "SELECT text, model, generated_at FROM alert_explanation "
            "WHERE alert_id = %s AND lang = %s AND decision_hash = %s",
            [alert_id, lang, decision_hash],
        )
        return cur.fetchone()


def save_explanation(*, alert_id: int, lang: str, decision_hash: str,
                     text: str, model: str) -> None:
    """Сохранить объяснение (идемпотентно по связке алерт+язык+версия решения)."""
    with connection.cursor() as cur:
        cur.execute(
            """
            INSERT INTO alert_explanation (alert_id, lang, decision_hash, text, model)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (alert_id, lang, decision_hash) DO UPDATE
                SET text = EXCLUDED.text, model = EXCLUDED.model, generated_at = now()
            """,
            [alert_id, lang, decision_hash, text, model],
        )


def delete_explanations(alert_id: int, lang: str | None = None) -> int:
    """Удалить кэш объяснений алерта (принудительная перегенерация)."""
    with connection.cursor() as cur:
        if lang:
            cur.execute("DELETE FROM alert_explanation WHERE alert_id=%s AND lang=%s",
                        [alert_id, lang])
        else:
            cur.execute("DELETE FROM alert_explanation WHERE alert_id=%s", [alert_id])
        return cur.rowcount


def recent_screenings(limit: int = 10) -> list[tuple]:
    """Последние проверенные адреса: (address, result, last_screened_at)."""
    with connection.cursor() as cur:
        cur.execute(
            "SELECT address, result, last_screened_at FROM address_screening "
            "ORDER BY last_screened_at DESC LIMIT %s",
            [limit],
        )
        return cur.fetchall()
