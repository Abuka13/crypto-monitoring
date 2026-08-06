"""Скрининг адреса по запросу: сбор данных на лету -> оценка -> вердикт.

Отличие от остального интерфейса: адреса может не быть в базе вообще. Поэтому
скрининг не выбирает данные, а ДОБЫВАЕТ их — идёт в Etherscan, сохраняет историю,
считает признаки, ML, граф и прогоняет через Decision Engine.

Порядок сознательно тот же, что и в пакетном конвейере, а оценку выполняет тот же
engine.score_one_wallet — вердикт скрининга обязан совпадать с тем, что система
скажет об этом кошельке в обычном режиме.

Дорого по времени (сетевые запросы) и расходует лимит API, поэтому результат
кэшируется на SCREEN_CACHE_MINUTES.
"""
from __future__ import annotations

import json
import logging
import re
import time
from pathlib import Path

from . import anomaly, db, features, graph as graph_mod, ingest
from .config import Config
from .risk import engine as risk_engine
from .sources.etherscan import EtherscanError, EtherscanSource

log = logging.getLogger(__name__)

ADDRESS_RE = re.compile(r"^0x[0-9a-fA-F]{40}$")
_SEED_PATH = Path(__file__).resolve().parent.parent / "data" / "labels_seed.json"


class ScreeningError(RuntimeError):
    """Ошибка скрининга с сообщением, пригодным для показа пользователю."""


def is_valid_address(address: str) -> bool:
    return bool(ADDRESS_RE.match((address or "").strip()))


def _seed_label_for(address: str) -> tuple[str, str] | None:
    """Метка адреса из сид-листа (mixer/exchange/sanctioned), если он там есть."""
    try:
        data = json.loads(_SEED_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    for entry in data.get("labels", []):
        if entry.get("address", "").lower() == address:
            return entry.get("label"), entry.get("source")
    return None


def _wei(value) -> str:
    return str(int(value or 0))


def screen_address(address: str, config: Config, force: bool = False) -> dict:
    """Проверить адрес: собрать данные (если нужно), оценить, вернуть вердикт."""
    address = (address or "").strip().lower()
    if not is_valid_address(address):
        raise ValueError("Неверный формат Ethereum-адреса: ожидается 0x и 40 hex-символов.")

    scfg = config.screening
    started = time.perf_counter()
    conn = db.connect(config.database_url)
    try:
        network_id = db.get_network_id(conn, "Ethereum")

        # 1) Кэш — не расходуем лимит Etherscan на повторную проверку.
        if not force:
            cached = db.get_screening_cache(conn, address, scfg.cache_minutes)
            if cached is not None:
                result, last_at, _ = cached
                result = dict(result)
                result["cached"] = True
                result["last_screened_at"] = last_at.isoformat()
                result["elapsed_ms"] = int((time.perf_counter() - started) * 1000)
                return result

        existing = db.get_wallet_by_address(conn, network_id, address)
        known_tx = existing[5] if existing else 0

        # 2) Данных нет или мало — идём в блокчейн.
        fetched = 0
        truncated = False
        collected = False
        if existing is None or known_tx < scfg.min_tx_for_fresh:
            source = EtherscanSource(
                api_key=config.etherscan_api_key,
                base_url=config.etherscan_base_url,
                chain_id=config.etherscan_chain_id,
                requests_per_second=config.requests_per_second,
            )
            try:
                stats = ingest.collect_by_address(
                    conn, source, network_id, address, max_transactions=scfg.max_tx
                )
            except EtherscanError as exc:
                raise ScreeningError(
                    "Не удалось получить данные из Etherscan (лимит запросов или "
                    f"недоступность сервиса). Попробуй ещё раз через минуту. [{exc}]"
                ) from exc
            except Exception as exc:  # сеть/таймаут — тоже понятное сообщение
                raise ScreeningError(
                    f"Ошибка обращения к Etherscan: {exc}"
                ) from exc
            fetched = stats.seen
            truncated = stats.seen >= scfg.max_tx
            collected = True

        # 3) Метка из сид-листа (санкции/миксер/биржа) — до расчёта риска.
        seed = _seed_label_for(address)
        if seed and seed[0]:
            db.upsert_wallet_label(conn, network_id, address, seed[0], seed[1])
            conn.commit()

        wallet = db.get_wallet_by_address(conn, network_id, address)
        if wallet is None:
            # Адрес валиден, но активности нет вообще — кошелёк даже не завёлся.
            return _empty_result(address, fetched, started, collected)

        wallet_id = wallet[0]

        # 4) Признаки поведения (вход для ML).
        rows = db.get_wallet_tx_full(conn, wallet_id)
        feats = features.compute_features(rows, wallet_id, config.risk)
        if feats is not None:
            db.upsert_wallet_features(conn, wallet_id, feats)
            conn.commit()

        # 5) Граф-метрики — локально по эго-сети, без пересборки всего графа.
        graph_feats = graph_mod.compute_for_wallet(conn, config.graph, wallet_id)
        graph_map = ({wallet_id: (float(graph_feats["graph_score"]),
                                  graph_feats["graph_explanation"])}
                     if graph_feats else {})

        # 6) Оценка тем же движком, что и пакетный расчёт (ML подмешается, если обучен).
        model = anomaly.AnomalyModel.load() if feats is not None else None
        risk_engine.score_one_wallet(conn, config.risk, wallet_id,
                                     model=model, dcfg=config.decision, graph_map=graph_map)

        result = _build_result(conn, wallet_id, address, fetched, truncated,
                               started, collected)
        db.save_screening(conn, address=address, network_id=network_id,
                          wallet_id=wallet_id, result=result, tx_fetched=fetched)
        conn.commit()
        return result
    finally:
        conn.close()


def _empty_result(address: str, fetched: int, started: float, collected: bool) -> dict:
    """Адрес валиден, но активности не найдено — это ответ, а не ошибка."""
    return {
        "address": address,
        "found": False,
        "no_activity": True,
        "label": None, "label_source": None,
        "risk_level": "LOW", "confidence": 0.9,
        "reasons": ["Активность по адресу не обнаружена — транзакций нет"],
        "sources": {},
        "summary": {
            "tx_count": 0, "total_received": "0", "total_sent": "0",
            "unique_counterparties": 0, "active_period_days": 0.0,
            "first_seen_at": None, "last_seen_at": None,
        },
        "tx_fetched": fetched, "truncated": False, "collected": collected,
        "cached": False, "elapsed_ms": int((time.perf_counter() - started) * 1000),
    }


def _build_result(conn, wallet_id: int, address: str, fetched: int,
                  truncated: bool, started: float, collected: bool) -> dict:
    """Собрать ответ скрининга из свежей оценки риска и агрегатов кошелька."""
    wallet = db.get_wallet_by_address(conn, db.get_network_id(conn, "Ethereum"), address)
    tx_count, received, sent, first_seen, last_seen = db.get_wallet_summary(conn, wallet_id)
    risk = db.get_latest_wallet_risk(conn, wallet_id)
    fmap = db.get_wallet_features_map(conn, [wallet_id]).get(wallet_id) or {}

    decision = (risk[6] if risk else None) or {}
    return {
        "address": address,
        "found": True,
        "no_activity": tx_count == 0,
        "label": wallet[3] if wallet else None,
        "label_source": wallet[4] if wallet else None,
        "risk_level": decision.get("level") or (risk[4] if risk else "LOW"),
        "confidence": decision.get("confidence", 0.5),
        "reasons": decision.get("reasons", []),
        "sources": decision.get("sources", {}),
        "scores": {
            "rule": float(risk[0]) if risk else 0.0,
            "ml": float(risk[1]) if risk else 0.0,
            "graph": float(risk[2]) if risk and risk[2] is not None else None,
            "final": float(risk[3]) if risk else 0.0,
        },
        "ml_explanation": risk[5] if risk else None,
        "summary": {
            "tx_count": tx_count,
            "total_received": _wei(received),   # wei строкой — точность в JS
            "total_sent": _wei(sent),
            "unique_counterparties": int(fmap.get("unique_counterparties") or 0),
            "active_period_days": float(fmap.get("active_period_days") or 0.0),
            "first_seen_at": first_seen.isoformat() if first_seen else None,
            "last_seen_at": last_seen.isoformat() if last_seen else None,
        },
        "tx_fetched": fetched,
        "truncated": truncated,
        "collected": collected,
        "cached": False,
        "elapsed_ms": int((time.perf_counter() - started) * 1000),
    }
