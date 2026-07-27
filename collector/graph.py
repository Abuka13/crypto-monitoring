"""Graph Analysis — оценка риска по ПОЛОЖЕНИЮ кошелька в сети переводов.

Блокчейн — это граф: кошельки = узлы, транзакции = рёбра (from → to). Правила
смотрят на сам кошелёк, ML — на его поведение, а граф — на то, С КЕМ он связан и
какое место занимает в сети. Метрики намеренно простые и объяснимые (без graph
neural networks — избыточно для задачи):

- in/out-степень — число уникальных входящих/исходящих связей;
- центральность — «проходность» узла (нормированная степень; betweenness слишком
  тяжёл на десятках тысяч узлов — O(V·E), поэтому берём лёгкую степенную меру);
- связь с рисковыми узлами — сколько прямых соседей помечены как миксер/санкции/
  мошенник (это самая важная метрика — «с кем связан»);
- транзитность — deposit-and-forward: близость входящего и исходящего ПОТОКА
  (упрощённо через объёмы; TODO: учесть длину цепочек и время удержания);
- веерность — массовый сбор (много входящих от разных) или распыление (много
  исходящих к разным).

Итог — graph_score (0..100): взвешенная сумма компонентов; веса и нормировки — в
GraphConfig (.env). Результат кладётся в wallet_graph_features, а оттуда
подмешивается в wallet_risk через Decision Engine.
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass

import networkx as nx

from . import db
from .config import GraphConfig

log = logging.getLogger(__name__)


@dataclass
class GraphStats:
    nodes: int = 0
    edges: int = 0
    scored: int = 0            # кошельков с посчитанным graph_score
    with_risky_links: int = 0  # из них — со связью с рисковым узлом

    def __str__(self) -> str:
        return (f"узлов={self.nodes}, рёбер={self.edges}, "
                f"оценено кошельков={self.scored} (со связью с рисковыми={self.with_risky_links})")


def build_graph(conn) -> tuple[nx.DiGraph, dict[int, str | None]]:
    """Построить направленный граф переводов и карту меток кошельков.

    Рёбра агрегируются по паре (отправитель→получатель): вес = сумма wei, count =
    число переводов. Собственные переводы (sender==receiver) пропускаем — они не
    создают связь между разными узлами. Карта меток нужна для метрики «связь с
    рисковыми узлами» (по всем кошелькам, не только по фокус-набору).
    """
    graph = nx.DiGraph()
    labels = db.get_all_wallet_labels(conn)  # {wallet_id: label|None}
    graph.add_nodes_from(labels.keys())

    for sender_id, receiver_id, count, total in db.get_aggregated_edges(conn):
        if sender_id == receiver_id:
            continue
        graph.add_edge(sender_id, receiver_id, weight=float(total or 0), count=int(count))

    return graph, labels


def _norm(value: float, ref: float) -> float:
    """Нормировка степени узла в 0..1 относительно ref (value=ref -> 1.0).

    Корень, а не логарифм: log1p слишком сильно сжимает шкалу — узел с 2 связями
    получал бы 0.18 при ref=500, что бессмысленно. sqrt даёт мягкий рост и при
    этом оставляет малые степени малыми (2 из 500 -> 0.06).
    """
    if value <= 0 or ref <= 0:
        return 0.0
    return min(1.0, math.sqrt(value / ref))


def compute_wallet_graph(graph: nx.DiGraph, labels: dict, wallet_id: int,
                         cfg: GraphConfig, n_nodes: int) -> dict:
    """Граф-метрики и graph_score одного кошелька."""
    preds = list(graph.predecessors(wallet_id))   # кто присылал
    succs = list(graph.successors(wallet_id))      # кому отправлял
    in_degree = len(preds)
    out_degree = len(succs)
    neighbors = set(preds) | set(succs)
    total_neighbors = len(neighbors)

    # Центральность: доля связей узла от максимально возможных (лёгкая мера).
    degree_centrality = ((in_degree + out_degree) / (n_nodes - 1)) if n_nodes > 1 else 0.0

    # Связь с рисковыми узлами — важнейшая метрика.
    risky = sum(1 for nb in neighbors if labels.get(nb) in cfg.risky_labels)
    risky_ratio = risky / total_neighbors if total_neighbors else 0.0

    # Транзитность (deposit-and-forward): близость входящего и исходящего ПОТОКА.
    in_flow = sum(graph[p][wallet_id]["weight"] for p in preds)
    out_flow = sum(graph[wallet_id][s]["weight"] for s in succs)
    hi = max(in_flow, out_flow)
    transit = (min(in_flow, out_flow) / hi) if (hi > 0 and in_degree and out_degree) else 0.0

    # Веерность: много уникальных входящих (сбор) / исходящих (распыление).
    fan_in = _norm(in_degree, cfg.fan_ref)
    fan_out = _norm(out_degree, cfg.fan_ref)

    # ---- Компоненты итоговой оценки (каждый 0..1) ----
    # Прямая связь с миксером/санкциями важна даже при одном таком соседе.
    c_risky = min(1.0, risky_ratio + 0.5 * min(risky, 2))
    c_centrality = _norm(in_degree + out_degree, cfg.centrality_ref)
    c_transit = transit
    c_fan = max(fan_in, fan_out)

    # Агрегация по принципу «независимых факторов риска» (noisy-OR), а не средним:
    #     score = 1 - Π(1 - w_i · c_i)
    # Взвешенное среднее РАЗБАВЛЯЕТ сильный сигнал отсутствующими: кошелёк,
    # у которого единственный сосед — миксер, максимизирует главную метрику, но
    # при усреднении получал бы ~55 из-за нулевых остальных. Здесь же каждый вес —
    # это максимальный вклад фактора в отдельности: связь с рисковым узлом сама по
    # себе даёт ~w_risky·100, а совпадение факторов усиливает оценку.
    weights = ((cfg.w_risky, c_risky), (cfg.w_centrality, c_centrality),
               (cfg.w_transit, c_transit), (cfg.w_fan, c_fan))
    residual = 1.0
    for w, c in weights:
        residual *= 1.0 - max(0.0, min(1.0, w * c))
    score = max(0.0, min(100.0, 100.0 * (1.0 - residual)))

    explanation = _explain(risky, risky_ratio, in_degree, out_degree,
                           c_centrality, transit, fan_in, fan_out, weights)

    return {
        "in_degree": in_degree,
        "out_degree": out_degree,
        "degree_centrality": degree_centrality,
        "risky_neighbors": risky,
        "risky_neighbor_ratio": risky_ratio,
        "transit_ratio": transit,
        "fan_in_ratio": fan_in,
        "fan_out_ratio": fan_out,
        "graph_score": round(score, 2),
        "graph_explanation": explanation,
    }


def _explain(risky, risky_ratio, in_deg, out_deg, c_centrality, transit,
             fan_in, fan_out, weights) -> str:
    """Топ-факторы графового риска человеческим языком (по вкладу в оценку)."""
    (w_risky, c_risky), (w_cent, _), (w_tr, _), (w_fan, _) = weights
    parts: list[tuple[float, str]] = []
    if risky > 0:
        parts.append((w_risky * c_risky,
                      f"прямая связь с рисковыми узлами: {risky} "
                      f"(миксер/санкции), доля {risky_ratio:.0%}"))
    if c_centrality >= 0.3:
        parts.append((w_cent * c_centrality,
                      f"высокая проходность: {in_deg} входящих / {out_deg} исходящих связей"))
    if transit >= 0.5:
        parts.append((w_tr * transit,
                      f"транзитный узел (входящий поток ≈ исходящему, {transit:.0%})"))
    fan = max(fan_in, fan_out)
    if fan >= 0.3:
        kind = f"сбор средств от {in_deg} адресов" if fan_in >= fan_out \
            else f"распыление средств на {out_deg} адресов"
        parts.append((w_fan * fan, f"веерность: {kind}"))

    parts.sort(reverse=True)
    top = [text for _, text in parts[:3]]
    return "; ".join(top) if top else "нейтральное положение в сети"


def compute_all(conn, cfg: GraphConfig) -> GraphStats:
    """Построить граф и посчитать graph-признаки для фокус-набора кошельков.

    Фокус-набор (кошельки с >= min_tx транзакций ИЛИ размеченные) ограничивает
    объём вычислений — весь граф сети строить не нужно, а соседей ищем по полному
    графу. Идемпотентно (upsert в wallet_graph_features).
    """
    stats = GraphStats()
    log.info("Построение графа переводов ...")
    graph, labels = build_graph(conn)
    stats.nodes = graph.number_of_nodes()
    stats.edges = graph.number_of_edges()
    log.info("Граф построен: %d узлов, %d рёбер", stats.nodes, stats.edges)

    focus = db.get_graph_focus_wallet_ids(conn, cfg.min_tx)
    total = len(focus)
    log.info("Кошельков к оценке (фокус-набор, >=%d tx или с меткой): %d", cfg.min_tx, total)

    for i, wallet_id in enumerate(focus, 1):
        if wallet_id not in graph:
            continue
        feats = compute_wallet_graph(graph, labels, wallet_id, cfg, stats.nodes)
        db.upsert_wallet_graph_features(conn, wallet_id, feats)
        stats.scored += 1
        if feats["risky_neighbors"] > 0:
            stats.with_risky_links += 1
        if i % 1000 == 0:
            conn.commit()
            log.info("  обработано %d / %d", i, total)

    conn.commit()
    return stats
