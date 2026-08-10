"""Схлопывание уже созданных алертов в алерты «сущность + причина».

Запуск:  python db/migrate_alerts_to_entities.py [--apply]

Без --apply показывает план, ничего не меняя.

Что делает:
1. Для каждого активного алерта восстанавливает сущность (кошелёк) и ключ причины
   из сохранённого решения (`decision`), как это теперь делает движок.
2. Группирует по (кошелёк, причина): оставляет САМЫЙ РАННИЙ алерт (у него честная
   дата обнаружения), переносит в него все транзакции-доказательства и берёт
   максимальный уровень из группы.
3. Дубликаты УДАЛЯЕТ.

Почему удалить, а не закрыть: доказательства полностью сохраняются в выжившем
алерте (alert_evidence), а статусы `closed` / `false_positive` означают «аналитик
разобрал». Пометить ими сотни машинно-схлопнутых дубликатов — значит исказить и
историю работы, и метрику «доля закрытых» на дашборде.
"""
from __future__ import annotations

import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from collector import db                      # noqa: E402
from collector.config import Config           # noqa: E402
from collector.risk.engine import (           # noqa: E402
    _entity_title, _subject_wallet, reason_key,
)

LEVEL_ORDER = {"low": 0, "medium": 1, "high": 2, "critical": 3}


def reason_key_from_decision(decision: dict | None, dcfg) -> str:
    """Ключ причины из сохранённого решения — ровно та же функция, что в движке."""
    if not decision:
        return "legacy"
    return reason_key(decision.get("sources") or {}, dcfg)


def main(apply: bool) -> int:
    cfg = Config.load()
    conn = db.connect(cfg.database_url)
    cur = conn.cursor()
    dcfg = cfg.decision

    cur.execute("""
        SELECT a.id, a.level, a.status, a.created_at, a.target_type,
               a.transaction_risk_id, a.wallet_risk_id,
               tr.transaction_id, t.sender_wallet_id, t.receiver_wallet_id,
               sw.label, rw.label,
               wr.wallet_id,
               COALESCE(tr.decision, wr.decision)
        FROM alert a
        LEFT JOIN transaction_risk tr ON tr.id = a.transaction_risk_id
        LEFT JOIN tx t   ON t.id  = tr.transaction_id
        LEFT JOIN wallet sw ON sw.id = t.sender_wallet_id
        LEFT JOIN wallet rw ON rw.id = t.receiver_wallet_id
        LEFT JOIN wallet_risk wr ON wr.id = a.wallet_risk_id
        WHERE a.status IN ('open', 'in_progress')
        ORDER BY a.id
    """)
    rows = cur.fetchall()
    print(f"Активных алертов до миграции: {len(rows)}")

    groups: dict[tuple, list] = defaultdict(list)
    skipped = 0
    for (aid, level, status, created, target_type, tr_id, wr_id,
         tx_id, sender_id, receiver_id, s_label, r_label, w_id, decision) in rows:
        if target_type == "transaction" and sender_id is not None:
            subject = _subject_wallet(sender_id, receiver_id, s_label, r_label, dcfg)
        elif w_id is not None:
            subject = w_id
        else:
            skipped += 1
            continue
        groups[(subject, reason_key_from_decision(decision, dcfg))].append(
            {"id": aid, "level": level, "created": created, "tx_id": tx_id}
        )

    survivors = len(groups)
    duplicates = sum(len(v) - 1 for v in groups.values())
    print(f"Групп (кошелёк + причина): {survivors}")
    print(f"Будет удалено дубликатов:  {duplicates}")
    if skipped:
        print(f"Пропущено (нет сущности):  {skipped}")

    top = sorted(groups.items(), key=lambda kv: len(kv[1]), reverse=True)[:5]
    addrs = db.get_wallet_addresses(conn, [w for (w, _), _ in top])
    print("\nСамые крупные схлопывания:")
    for (wallet_id, reason), items in top:
        print(f"  {len(items):4} -> 1   {addrs.get(wallet_id, '?')[:20]}…  [{reason[:52]}]")

    if not apply:
        print("\nЭто предпросмотр. Повтори с --apply, чтобы применить.")
        return 0

    merged = removed = 0
    for (wallet_id, reason), items in groups.items():
        items.sort(key=lambda x: (x["created"], x["id"]))
        keeper = items[0]
        level = max((i["level"] for i in items), key=lambda l: LEVEL_ORDER.get(l, 0))

        cur.execute(
            "UPDATE alert SET wallet_id=%s, reason_key=%s, level=%s WHERE id=%s",
            (wallet_id, reason, level, keeper["id"]),
        )
        for it in items:
            if it["tx_id"] is not None:
                cur.execute(
                    "INSERT INTO alert_evidence (alert_id, transaction_id) VALUES (%s, %s) "
                    "ON CONFLICT DO NOTHING",
                    (keeper["id"], it["tx_id"]),
                )
        dup_ids = [i["id"] for i in items[1:]]
        if dup_ids:
            cur.execute("DELETE FROM alert WHERE id = ANY(%s)", (dup_ids,))
            removed += len(dup_ids)

        summary = db.recalc_alert_evidence(conn, keeper["id"])
        addr = db.get_wallet_addresses(conn, [wallet_id]).get(wallet_id, "")
        db.set_alert_title(conn, keeper["id"], _entity_title(addr, reason, summary))
        merged += 1

    conn.commit()
    print(f"\nГотово: оставлено {merged} алертов, удалено дубликатов {removed}.")

    cur.execute("""SELECT level, count(*) FROM alert
                   WHERE status IN ('open','in_progress') GROUP BY level""")
    print("Активные алерты после миграции:", dict(cur.fetchall()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main("--apply" in sys.argv))
