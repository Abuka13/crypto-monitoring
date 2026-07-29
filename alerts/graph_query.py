"""Эго-сеть кошелька для страницы «Граф потоков».

Весь граф (66k узлов) не отдаётся никогда: строим подграф вокруг центрального
кошелька на ограниченную глубину, с жёстким лимитом узлов. Соседи ранжируются по
объёму потока — если их больше лимита, отдаём самых значимых и помечаем ответ
truncated, чтобы интерфейс честно показал «показано N из M».

Запросы — raw SQL: агрегация рёбер и выбор последней оценки риска через LATERAL
на ORM выражаются плохо и работают медленнее.
"""
from __future__ import annotations

from django.db import connection

MAX_DEPTH = 2
DEFAULT_LIMIT = 60
MAX_LIMIT = 200


def _rows(sql: str, params: list) -> list[tuple]:
    with connection.cursor() as cur:
        cur.execute(sql, params)
        return cur.fetchall()


def resolve_center(address: str | None, wallet_id: str | None) -> tuple[int, str] | None:
    """Найти центральный кошелёк по адресу или id. -> (id, address) или None."""
    if wallet_id:
        rows = _rows("SELECT id, address FROM wallet WHERE id = %s", [wallet_id])
    elif address:
        rows = _rows("SELECT id, address FROM wallet WHERE address = %s",
                     [address.strip().lower()])
    else:
        return None
    return (rows[0][0], rows[0][1]) if rows else None


# Соседи набора кошельков, отранжированные по объёму потока (обе стороны).
_NEIGHBOURS_SQL = """
WITH e AS (
    SELECT receiver_wallet_id AS other, COUNT(*) AS c, SUM(amount) AS s
    FROM tx WHERE sender_wallet_id = ANY(%s) GROUP BY 1
    UNION ALL
    SELECT sender_wallet_id AS other, COUNT(*) AS c, SUM(amount) AS s
    FROM tx WHERE receiver_wallet_id = ANY(%s) GROUP BY 1
),
agg AS (
    SELECT other, SUM(c) AS cnt, SUM(s) AS total
    FROM e WHERE NOT (other = ANY(%s)) GROUP BY other
)
SELECT other, cnt, total,
       (SELECT count(*) FROM agg) AS total_neighbors
FROM agg ORDER BY total DESC NULLS LAST, cnt DESC LIMIT %s
"""


def _neighbours(frontier: list[int], exclude: list[int], limit: int) -> tuple[list[int], int]:
    """Топ-limit соседей набора frontier. -> (id соседей, всего соседей)."""
    if not frontier or limit <= 0:
        return [], 0
    rows = _rows(_NEIGHBOURS_SQL, [frontier, frontier, exclude, limit])
    if not rows:
        return [], 0
    return [r[0] for r in rows], rows[0][3]


# Рёбра внутри итогового набора узлов (включая связи соседей между собой).
_EDGES_SQL = """
SELECT sender_wallet_id, receiver_wallet_id, COUNT(*), SUM(amount)
FROM tx
WHERE sender_wallet_id = ANY(%s) AND receiver_wallet_id = ANY(%s)
  AND sender_wallet_id <> receiver_wallet_id
GROUP BY 1, 2
"""

# Данные узлов: метка, агрегаты, граф-оценка и ПОСЛЕДНЯЯ оценка риска.
_NODES_SQL = """
SELECT w.id, w.address, w.label, w.label_source, w.transaction_count,
       g.graph_score, r.risk_level, r.final_score
FROM wallet w
LEFT JOIN wallet_graph_features g ON g.wallet_id = w.id
LEFT JOIN LATERAL (
    SELECT risk_level, final_score FROM wallet_risk
    WHERE wallet_id = w.id ORDER BY created_at DESC, id DESC LIMIT 1
) r ON TRUE
WHERE w.id = ANY(%s)
"""


def build_ego_network(center_id: int, depth: int, limit: int) -> dict:
    """Подграф вокруг center_id: узлы + рёбра, не более limit узлов."""
    depth = max(1, min(depth, MAX_DEPTH))
    limit = max(5, min(limit, MAX_LIMIT))

    node_ids = [center_id]
    node_depth = {center_id: 0}
    frontier = [center_id]
    truncated = False
    total_neighbors = 0

    for level in range(1, depth + 1):
        room = limit - len(node_ids)
        if room <= 0:
            truncated = True
            break
        found, total = _neighbours(frontier, node_ids, room)
        if level == 1:
            total_neighbors = total
        if total > len(found):
            truncated = True
        if not found:
            break
        for wid in found:
            node_depth[wid] = level
        node_ids.extend(found)
        frontier = found

    edges = [
        {
            "source": s,
            "target": t,
            "tx_count": c,
            "total_amount": str(int(total or 0)),  # wei строкой — точность в JS
        }
        for s, t, c, total in _rows(_EDGES_SQL, [node_ids, node_ids])
    ]

    nodes = []
    for (wid, address, label, label_source, tx_count,
         graph_score, risk_level, final_score) in _rows(_NODES_SQL, [node_ids]):
        nodes.append({
            "id": wid,
            "address": address,
            "label": label,
            "label_source": label_source,
            "risk_level": risk_level or "LOW",
            "final_score": float(final_score) if final_score is not None else 0.0,
            "graph_score": float(graph_score) if graph_score is not None else None,
            "tx_count": tx_count,
            "is_center": wid == center_id,
            "depth": node_depth.get(wid, 0),
        })
    # Центр первым — интерфейсу удобно и не зависит от порядка БД.
    nodes.sort(key=lambda n: (not n["is_center"], n["depth"], -n["final_score"]))

    return {
        "depth": depth,
        "limit": limit,
        "truncated": truncated,
        "total_neighbors": total_neighbors,
        "shown_neighbors": len(nodes) - 1,
        "nodes": nodes,
        "edges": edges,
    }
