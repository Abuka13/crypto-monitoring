"""Конфигурация из .env (секреты не хардкодятся)."""
from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


class ConfigError(RuntimeError):
    """Нет обязательной переменной окружения."""


def _required(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise ConfigError(f"Не задана переменная {name} (см. .env.example).")
    return value


ETH = 10 ** 18  # 1 ETH в wei


@dataclass(frozen=True)
class RiskConfig:
    """Пороги Rule Engine (wei как int). Меняются через .env без правки кода."""

    large_amount_threshold_wei: int          # «Большая сумма»
    new_wallet_max_age_days: int             # «Новый кошелёк»: возраст
    high_frequency_count: int                # «Высокая частота»: N транзакций
    high_frequency_window_hours: int         #   в окне M часов
    structuring_small_amount_wei: int        # «Дробление»: порог мелкой суммы
    structuring_min_count: int               #   и минимум таких операций
    # Веса гибридного скоринга: final = weight_rule*rule + weight_ml*ml (сумма = 1).
    weight_rule: float
    weight_ml: float

    @staticmethod
    def load() -> "RiskConfig":
        return RiskConfig(
            large_amount_threshold_wei=int(
                os.getenv("RISK_LARGE_AMOUNT_WEI", str(10 * ETH))
            ),
            new_wallet_max_age_days=int(os.getenv("RISK_NEW_WALLET_MAX_AGE_DAYS", "30")),
            high_frequency_count=int(os.getenv("RISK_HIGH_FREQ_COUNT", "50")),
            high_frequency_window_hours=int(os.getenv("RISK_HIGH_FREQ_WINDOW_HOURS", "24")),
            structuring_small_amount_wei=int(
                os.getenv("RISK_STRUCTURING_SMALL_WEI", str(ETH // 100))
            ),
            structuring_min_count=int(os.getenv("RISK_STRUCTURING_MIN_COUNT", "30")),
            weight_rule=float(os.getenv("RISK_WEIGHT_RULE", "0.6")),
            weight_ml=float(os.getenv("RISK_WEIGHT_ML", "0.4")),
        )


def _csv_set(name: str, default: str) -> frozenset[str]:
    return frozenset(x.strip() for x in os.getenv(name, default).split(",") if x.strip())


@dataclass(frozen=True)
class DecisionConfig:
    """Пороги и списки Decision Engine. Всё калибруется через .env, без правки кода."""

    rule_critical: float      # rule_score для CRITICAL (при подтверждении)
    rule_high: float          # rule_score для HIGH
    rule_medium: float        # rule_score для MEDIUM
    ml_high: float            # «высокий» ml_score
    graph_high: float         # «высокий» graph_score (задел)
    strong_rules: frozenset[str]        # правила повышенной значимости
    hard_signal_labels: frozenset[str]  # метки уровня Hard Signal
    trusted_labels: frozenset[str]      # известные легитимные (биржи): ИИ/граф в
                                        # одиночку по ним алерт не создают

    @staticmethod
    def load() -> "DecisionConfig":
        return DecisionConfig(
            rule_critical=float(os.getenv("DECISION_RULE_CRITICAL", "75")),
            rule_high=float(os.getenv("DECISION_RULE_HIGH", "50")),
            rule_medium=float(os.getenv("DECISION_RULE_MEDIUM", "25")),
            ml_high=float(os.getenv("DECISION_ML_HIGH", "70")),
            graph_high=float(os.getenv("DECISION_GRAPH_HIGH", "70")),
            strong_rules=_csv_set("DECISION_STRONG_RULES", "Связь с миксером"),
            hard_signal_labels=_csv_set(
                "DECISION_HARD_SIGNAL_LABELS", "sanctioned,blacklist,fraud"),
            trusted_labels=_csv_set("DECISION_TRUSTED_LABELS", "exchange"),
        )


@dataclass(frozen=True)
class GraphConfig:
    """Веса и нормировки Graph Analysis. Всё калибруется через .env, без правки кода."""

    min_tx: int                       # кошельки с >= min_tx tx попадают в фокус-набор
    risky_labels: frozenset[str]      # метки соседей, считающихся «рисковыми»
    centrality_ref: int               # степень узла, дающая полную центральность (=1.0)
    fan_ref: int                      # число связей, дающее полную веерность (=1.0)
    # Веса = МАКСИМАЛЬНЫЙ вклад фактора по отдельности (агрегация noisy-OR, не среднее).
    # Сумма не обязана равняться 1: 0.75 у «связи с рисковыми» означает, что один
    # такой признак сам по себе даёт ~75 баллов, а совпадение факторов усиливает.
    w_risky: float                    # связь с рисковыми узлами (самая важная метрика)
    w_centrality: float               # проходность/центральность
    w_transit: float                  # транзитность (deposit-and-forward)
    w_fan: float                      # веерность (массовый сбор/распыление)

    @staticmethod
    def load() -> "GraphConfig":
        return GraphConfig(
            min_tx=int(os.getenv("GRAPH_MIN_TX", "3")),
            risky_labels=_csv_set("GRAPH_RISKY_LABELS", "mixer,sanctioned,fraud,blacklist"),
            centrality_ref=int(os.getenv("GRAPH_CENTRALITY_REF", "500")),
            fan_ref=int(os.getenv("GRAPH_FAN_REF", "100")),
            w_risky=float(os.getenv("GRAPH_W_RISKY", "0.75")),
            w_centrality=float(os.getenv("GRAPH_W_CENTRALITY", "0.35")),
            w_transit=float(os.getenv("GRAPH_W_TRANSIT", "0.30")),
            w_fan=float(os.getenv("GRAPH_W_FAN", "0.20")),
        )


@dataclass(frozen=True)
class ScreeningConfig:
    """Скрининг адреса по запросу: сбор из Etherscan на лету + кэш результата."""

    max_tx: int          # сколько транзакций тянуть максимум (лимиты и время ответа)
    cache_minutes: int   # не дёргать Etherscan повторно в течение N минут
    min_tx_for_fresh: int  # если в базе меньше N транзакций — идём в Etherscan

    @staticmethod
    def load() -> "ScreeningConfig":
        return ScreeningConfig(
            max_tx=int(os.getenv("SCREEN_MAX_TX", "300")),
            cache_minutes=int(os.getenv("SCREEN_CACHE_MINUTES", "15")),
            min_tx_for_fresh=int(os.getenv("SCREEN_MIN_TX_FOR_FRESH", "5")),
        )


@dataclass(frozen=True)
class Config:
    database_url: str
    etherscan_api_key: str
    etherscan_base_url: str        # V2 multichain-эндпоинт
    etherscan_chain_id: int
    requests_per_second: float     # лимит бесплатного ключа ~5/с
    risk: RiskConfig
    decision: DecisionConfig
    graph: GraphConfig
    screening: ScreeningConfig

    @staticmethod
    def load() -> "Config":
        return Config(
            database_url=_required("DATABASE_URL"),
            etherscan_api_key=_required("ETHERSCAN_API_KEY"),
            etherscan_base_url=os.getenv(
                "ETHERSCAN_BASE_URL", "https://api.etherscan.io/v2/api"
            ),
            etherscan_chain_id=int(os.getenv("ETHERSCAN_CHAIN_ID", "1")),
            requests_per_second=float(os.getenv("ETHERSCAN_RPS", "4")),
            risk=RiskConfig.load(),
            decision=DecisionConfig.load(),
            graph=GraphConfig.load(),
            screening=ScreeningConfig.load(),
        )
