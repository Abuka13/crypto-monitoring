"""Слежение за вершиной блокчейна: тянет новые блоки в БД. Курсор в файле
состояния (продолжает после перезапуска); сбой цикла не роняет слежение."""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path

from . import db, ingest
from .config import RiskConfig
from .risk import engine as risk_engine
from .sources.base import BlockchainSource

log = logging.getLogger(__name__)

# Файл состояния в корне проекта (в .gitignore).
_STATE_PATH = Path(__file__).resolve().parent.parent / ".collector_state.json"


def _load_cursor(network_name: str) -> int | None:
    try:
        data = json.loads(_STATE_PATH.read_text(encoding="utf-8"))
        value = data.get("last_block", {}).get(network_name)
        return int(value) if value is not None else None
    except (FileNotFoundError, ValueError, json.JSONDecodeError):
        return None


def _save_cursor(network_name: str, block_number: int) -> None:
    data = {}
    try:
        data = json.loads(_STATE_PATH.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError, json.JSONDecodeError):
        data = {}
    data.setdefault("last_block", {})[network_name] = block_number
    _STATE_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")


def run_follow(
    conn,
    source: BlockchainSource,
    network_id: int,
    *,
    poll_interval: float = 15.0,
    max_blocks_per_cycle: int = 10,
    from_block: int | None = None,
    score: bool = False,
    risk_cfg: RiskConfig | None = None,
    model=None,
    dcfg=None,
) -> int:
    """Цикл слежения (Ctrl+C — стоп).

    from_block задан -> с него; иначе курсор -> с сохранённого; иначе -> с вершины.
    score=True -> после каждого блока инкрементальный расчёт риска по его данным.
    """
    name = source.network_name

    if from_block is not None:
        cursor = from_block - 1
        log.info("Старт слежения с блока %d (--from-block)", from_block)
    else:
        saved = _load_cursor(name)
        if saved is not None:
            cursor = saved
            log.info("Продолжаем с сохранённого блока %d", cursor + 1)
        else:
            cursor = source.get_latest_block_number()
            log.info("Сохранённого состояния нет — следим с текущей вершины (%d)", cursor)

    mode = "сбор + расчёт риска" if score else "только сбор"
    print(f"Слежение за новыми блоками {name} ({mode}). Остановка — Ctrl+C.")

    while True:
        try:
            tip = source.get_latest_block_number()
            if tip <= cursor:
                time.sleep(poll_interval)  # новых блоков нет
                continue

            target = min(tip, cursor + max_blocks_per_cycle)
            behind = tip - cursor
            for block in range(cursor + 1, target + 1):
                stats = ingest.collect_by_block(conn, source, network_id, block)
                _save_cursor(name, block)
                cursor = block
                log.info(
                    "Блок %d обработан (%s); отставание от вершины: %d",
                    block, stats, tip - block,
                )
                # Риск только по этому блоку (сбой расчёта не роняет сбор).
                if score and stats.inserted:
                    try:
                        rstats = risk_engine.score_block(conn, risk_cfg, network_id, block, model=model, dcfg=dcfg)
                        log.info("Риск по блоку %d: %s", block, rstats)
                    except Exception as exc:
                        conn.rollback()
                        log.error("Не удалось посчитать риск по блоку %d: %s", block, exc)

            if behind > max_blocks_per_cycle:  # сильно отстаём — догоняем без паузы
                continue
            time.sleep(poll_interval)

        except KeyboardInterrupt:
            print("\nОстановлено. Последний обработанный блок:", cursor)
            return 0
        except Exception as exc:  # сбойный цикл не роняет слежение
            log.error("Сбой цикла слежения: %s. Повтор через %ss", exc, poll_interval)
            time.sleep(poll_interval)
