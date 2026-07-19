"""CLI: сбор данных, расчёт риска, слежение. См. COMMANDS.md."""
from __future__ import annotations

import argparse
import logging
import sys

from . import db, features, follow, ingest
from .config import Config, ConfigError
from .risk import engine as risk_engine
from .sources.etherscan import EtherscanSource


def _make_source(config):
    return EtherscanSource(
        api_key=config.etherscan_api_key,
        base_url=config.etherscan_base_url,
        chain_id=config.etherscan_chain_id,
        requests_per_second=config.requests_per_second,
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="collector",
        description="Сбор транзакций Ethereum и расчёт риска (Rule Engine).",
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--address", help="Ethereum-адрес для сбора транзакций")
    group.add_argument("--block", type=int, help="Номер блока для сбора транзакций")
    group.add_argument(
        "--follow", action="store_true",
        help="Следить за новыми блоками: постоянно подтягивать свежие транзакции",
    )
    group.add_argument(
        "--score-risk", action="store_true",
        help="Рассчитать риск и сгенерировать алерты по уже собранным данным",
    )
    group.add_argument(
        "--seed-labels", action="store_true",
        help="Применить метки адресов из data/labels_seed.json (идемпотентно)",
    )
    group.add_argument(
        "--compute-features", action="store_true",
        help="Посчитать числовые признаки кошельков (вход для ML) в wallet_features",
    )
    group.add_argument(
        "--reset-data", action="store_true",
        help="Очистить данные (wallet/tx/оценки/алерты), сохранив справочники "
             "blockchain_network и rule. Требует --yes для подтверждения.",
    )
    parser.add_argument(
        "--max", type=int, default=None,
        help="Ограничить число транзакций (полезно на бесплатном ключе)",
    )
    parser.add_argument(
        "--poll-interval", type=float, default=15.0,
        help="Пауза между опросами вершины цепочки, сек (для --follow; по умолчанию 15)",
    )
    parser.add_argument(
        "--max-blocks-per-cycle", type=int, default=10,
        help="Максимум блоков за один цикл слежения (для --follow; по умолчанию 10)",
    )
    parser.add_argument(
        "--from-block", type=int, default=None,
        help="С какого блока начать слежение (для --follow; иначе — с текущей вершины)",
    )
    parser.add_argument(
        "--score", action="store_true",
        help="Вместе с --follow: после каждого блока считать риск и алерты по его данным",
    )
    parser.add_argument(
        "--labels-file", default=None,
        help="Путь к сид-файлу меток (по умолчанию data/labels_seed.json)",
    )
    parser.add_argument(
        "--min-tx", type=int, default=features.DEFAULT_MIN_TX,
        help=f"Минимум транзакций для расчёта признаков (по умолчанию {features.DEFAULT_MIN_TX})",
    )
    parser.add_argument(
        "--yes", action="store_true",
        help="Подтвердить удаление для --reset-data без дополнительного запроса",
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true", help="Подробный лог"
    )
    return parser


def _run_follow(conn, config, args) -> int:
    source = _make_source(config)
    network_id = db.get_network_id(conn, source.network_name)
    return follow.run_follow(
        conn, source, network_id,
        poll_interval=args.poll_interval,
        max_blocks_per_cycle=args.max_blocks_per_cycle,
        from_block=args.from_block,
        score=args.score,
        risk_cfg=config.risk,
    )


def _run_collect(conn, config, args) -> int:
    source = _make_source(config)
    network_id = db.get_network_id(conn, source.network_name)
    if args.address:
        print(f"Сбор транзакций для адреса {args.address} ...")
        stats = ingest.collect_by_address(
            conn, source, network_id, args.address, max_transactions=args.max
        )
    else:
        print(f"Сбор транзакций для блока {args.block} ...")
        stats = ingest.collect_by_block(conn, source, network_id, args.block)
    print(f"Готово: {stats}")
    return 0


def _run_score_risk(conn, config) -> int:
    print("Расчёт риска по собранным данным (Rule Engine) ...")
    stats = risk_engine.score_risk(conn, config.risk)
    print(f"Готово: {stats}")
    if stats.skipped_rules:
        print(f"Пропущены правила без реализации: {', '.join(stats.skipped_rules)}")

    alerts = db.get_sample_alerts(conn, limit=5)
    if not alerts:
        print("\nАлертов не создано (ни одна оценка не превысила порог 50).")
        return 0

    print(f"\nПримеры алертов (свежие {len(alerts)}):")
    for target_type, level, status, title, description, created_at in alerts:
        print(f"  [{level.upper():6}] [{status}] {title}")
        print(f"          цель: {target_type} | {description}")
    return 0


def _run_seed_labels(conn, args) -> int:
    import json
    from pathlib import Path

    path = Path(args.labels_file or Path(__file__).resolve().parent.parent / "data" / "labels_seed.json")
    if not path.exists():
        print(f"Сид-файл не найден: {path}", file=sys.stderr)
        return 2

    data = json.loads(path.read_text(encoding="utf-8"))
    entries = data.get("labels", [])
    network_id = db.get_network_id(conn, "Ethereum")

    # Счётчики по типу метки: {label: {created, updated, unchanged}}
    report: dict[str, dict[str, int]] = {}
    for e in entries:
        outcome = db.upsert_wallet_label(
            conn, network_id, e["address"], e["label"], e["source"]
        )
        report.setdefault(e["label"], {"created": 0, "updated": 0, "unchanged": 0})
        report[e["label"]][outcome] += 1
    conn.commit()

    print(f"Метки применены из {path.name} (записей: {len(entries)}):")
    for label, c in sorted(report.items()):
        print(f"  {label:11}: создано={c['created']}, обновлено={c['updated']}, без изменений={c['unchanged']}")
    return 0


def _run_compute_features(conn, config, args) -> int:
    print(f"Расчёт признаков кошельков (>= {args.min_tx} транзакций) ...")
    stats = features.compute_all(conn, config.risk, min_tx=args.min_tx)
    print(f"Готово: {stats}")
    _print_feature_summary(conn)
    return 0


def _print_feature_summary(conn) -> None:
    """Сводка для проверки осмысленности признаков."""
    cur = conn.cursor()
    cur.execute("SELECT count(*) FROM wallet_features")
    print(f"\nВсего строк признаков: {cur.fetchone()[0]}")

    cur.execute(
        """
        SELECT AVG(tx_total)::numeric(10,1), AVG(unique_counterparties)::numeric(10,1),
               AVG(counterparty_spread)::numeric(10,3), AVG(small_tx_ratio)::numeric(10,3),
               AVG(transit_ratio)::numeric(10,3), AVG(max_tx_24h)::numeric(10,1)
        FROM wallet_features
        """
    )
    a = cur.fetchone()
    if a and a[0] is not None:
        print("Средние: tx_total={0}, контрагентов={1}, разброс={2}, "
              "доля мелких={3}, транзитность={4}, макс/24ч={5}".format(*a))

    print("\nТоп-5 по числу транзакций:")
    cur.execute(
        """
        SELECT w.address, f.tx_total, f.unique_counterparties, w.label
        FROM wallet_features f JOIN wallet w ON w.id = f.wallet_id
        ORDER BY f.tx_total DESC LIMIT 5
        """
    )
    for addr, txt, uc, label in cur.fetchall():
        print(f"  {addr[:14]}…  tx={txt:<6} контрагентов={uc:<5} {('['+label+']') if label else ''}")

    print("\nSanity-check — размеченные биржи (ожидаем крупные признаки):")
    cur.execute(
        """
        SELECT w.address, f.tx_total, f.unique_counterparties, f.avg_tx_per_day::numeric(10,1)
        FROM wallet_features f JOIN wallet w ON w.id = f.wallet_id
        WHERE w.label = 'exchange' ORDER BY f.tx_total DESC
        """
    )
    rows = cur.fetchall()
    for addr, txt, uc, freq in rows:
        print(f"  {addr[:14]}…  tx={txt:<6} контрагентов={uc:<5} tx/день={freq}")
    if not rows:
        print("  (нет бирж с достаточным числом транзакций для признаков)")


def _run_reset(conn, assume_yes: bool) -> int:
    counts = db.count_data_tables(conn)
    total = sum(counts.values())
    summary = ", ".join(f"{t}={n}" for t, n in counts.items())

    if total == 0:
        print("Таблицы данных уже пусты — удалять нечего.")
        return 0

    if not assume_yes:
        print("Будут удалены данные (справочники blockchain_network и rule сохранятся):")
        print(f"  {summary}")
        print("\nЭто необратимо. Повтори команду с флагом --yes, чтобы удалить:")
        print("  python -m collector --reset-data --yes")
        return 1

    deleted = db.reset_data(conn)
    print("Данные удалены (справочники сохранены):")
    print("  " + ", ".join(f"{t}={n}" for t, n in deleted.items()))
    return 0


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    try:
        config = Config.load()
    except ConfigError as exc:
        print(f"Ошибка конфигурации: {exc}", file=sys.stderr)
        return 2

    conn = db.connect(config.database_url)
    try:
        if args.seed_labels:
            return _run_seed_labels(conn, args)
        if args.compute_features:
            return _run_compute_features(conn, config, args)
        if args.reset_data:
            return _run_reset(conn, args.yes)
        if args.follow:
            return _run_follow(conn, config, args)
        if args.score_risk:
            return _run_score_risk(conn, config)
        return _run_collect(conn, config, args)
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
