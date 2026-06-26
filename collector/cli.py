"""Точка входа сбора данных.

Примеры:
  python -m collector --address 0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045 --max 25
  python -m collector --block 19000000
"""
from __future__ import annotations

import argparse
import logging
import sys

from . import db, ingest
from .config import Config, ConfigError
from .sources.etherscan import EtherscanSource


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="collector",
        description="Сбор транзакций Ethereum через Etherscan в PostgreSQL.",
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--address", help="Ethereum-адрес для сбора транзакций")
    group.add_argument("--block", type=int, help="Номер блока для сбора транзакций")
    parser.add_argument(
        "--max", type=int, default=None,
        help="Ограничить число транзакций (полезно на бесплатном ключе)",
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true", help="Подробный лог"
    )
    return parser


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

    source = EtherscanSource(
        api_key=config.etherscan_api_key,
        base_url=config.etherscan_base_url,
        chain_id=config.etherscan_chain_id,
        requests_per_second=config.requests_per_second,
    )

    conn = db.connect(config.database_url)
    try:
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
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
