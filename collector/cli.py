"""Точка входа.

Сбор данных:
  python -m collector --address 0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045 --max 25
  python -m collector --block 19000000

Расчёт риска по уже собранным данным (Rule Engine):
  python -m collector --score-risk -v
"""
from __future__ import annotations

import argparse
import logging
import sys

from . import db, ingest
from .config import Config, ConfigError
from .risk import engine as risk_engine
from .sources.etherscan import EtherscanSource


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="collector",
        description="Сбор транзакций Ethereum и расчёт риска (Rule Engine).",
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--address", help="Ethereum-адрес для сбора транзакций")
    group.add_argument("--block", type=int, help="Номер блока для сбора транзакций")
    group.add_argument(
        "--score-risk", action="store_true",
        help="Рассчитать риск и сгенерировать алерты по уже собранным данным",
    )
    parser.add_argument(
        "--max", type=int, default=None,
        help="Ограничить число транзакций (полезно на бесплатном ключе)",
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true", help="Подробный лог"
    )
    return parser


def _run_collect(conn, config, args) -> int:
    source = EtherscanSource(
        api_key=config.etherscan_api_key,
        base_url=config.etherscan_base_url,
        chain_id=config.etherscan_chain_id,
        requests_per_second=config.requests_per_second,
    )
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
        print("\nАлертов не создано (ни одна оценка не достигла порога HIGH=50).")
        return 0

    print(f"\nПримеры алертов (свежие {len(alerts)}):")
    for target_type, level, status, title, description, created_at in alerts:
        print(f"  [{level.upper():6}] [{status}] {title}")
        print(f"          цель: {target_type} | {description}")
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
        if args.score_risk:
            return _run_score_risk(conn, config)
        return _run_collect(conn, config, args)
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
