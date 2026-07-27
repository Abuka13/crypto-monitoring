"""Сериализаторы API. wei -> строки (точность в JS); баллы риска — числа.
Сработавшие правила парсим из alert.description."""
from __future__ import annotations

import re
from decimal import Decimal

from rest_framework import serializers

from .models import Alert, Rule, Tx, Wallet, WalletFeatures, WalletGraphFeatures
from .transitions import VALID_STATUSES

# Формат описания от Rule Engine: «Сработавшие правила: Имя (+балл); ...».
# Якорим на «(+число)» — имя может содержать свои скобки.
_REASON_PREFIX = "Сработавшие правила:"
_RULE_RE = re.compile(r"\s*(.+?)\s*\(\+([\d.]+)\)\s*(?:;|$)")


def _wei(value: Decimal | None) -> str | None:
    """wei -> строка (без потери точности). None остаётся None."""
    return None if value is None else str(value)


def parse_fired_rules(description: str | None) -> list[dict]:
    """Вытащить список сработавших правил с баллами из описания алерта."""
    if not description:
        return []
    text = description
    idx = text.find(_REASON_PREFIX)
    if idx != -1:
        text = text[idx + len(_REASON_PREFIX):]
    return [
        {"name": name.strip(), "score": float(score)}
        for name, score in _RULE_RE.findall(text)
    ]


def _related_risk(alert: Alert):
    """Связанная оценка риска (одна из двух) или None."""
    return alert.transaction_risk or alert.wallet_risk


def _graph_explanation(wallet: Wallet) -> str | None:
    """Объяснение графового риска кошелька (если граф посчитан)."""
    try:
        return wallet.graph_features.graph_explanation
    except WalletGraphFeatures.DoesNotExist:
        return None


class AlertListSerializer(serializers.ModelSerializer):
    """Элемент списка GET /api/alerts/."""

    final_score = serializers.SerializerMethodField()

    class Meta:
        model = Alert
        fields = [
            "id", "target_type", "level", "status",
            "title", "description", "created_at", "resolved_at",
            "final_score",
        ]

    def get_final_score(self, obj: Alert) -> float | None:
        risk = _related_risk(obj)
        return float(risk.final_score) if risk else None


class AlertDetailSerializer(serializers.ModelSerializer):
    """Детали GET /api/alerts/{id}/ с контекстом «почему сработало»."""

    final_score = serializers.SerializerMethodField()
    risk_level = serializers.SerializerMethodField()
    fired_rules = serializers.SerializerMethodField()
    context = serializers.SerializerMethodField()
    decision = serializers.SerializerMethodField()

    class Meta:
        model = Alert
        fields = [
            "id", "target_type", "level", "status",
            "title", "description", "created_at", "resolved_at",
            "final_score", "risk_level", "fired_rules", "context", "decision",
        ]

    def get_decision(self, obj: Alert) -> dict | None:
        """Решение Decision Engine: уровень, уверенность, причины, вклад источников."""
        risk = _related_risk(obj)
        return getattr(risk, "decision", None) if risk else None

    def get_final_score(self, obj: Alert) -> float | None:
        risk = _related_risk(obj)
        return float(risk.final_score) if risk else None

    def get_risk_level(self, obj: Alert) -> str | None:
        risk = _related_risk(obj)
        return risk.risk_level if risk else None

    def get_fired_rules(self, obj: Alert) -> list[dict]:
        """Сработавшие правила: из решения Decision Engine, иначе — из описания."""
        risk = _related_risk(obj)
        decision = getattr(risk, "decision", None) if risk else None
        if decision:
            fired = (decision.get("sources", {}).get("rule", {}) or {}).get("fired")
            if fired is not None:
                return fired
        return parse_fired_rules(obj.description)

    def get_context(self, obj: Alert) -> dict | None:
        """Подробности объекта, к которому относится алерт (tx или кошелёк)."""
        if obj.target_type == "transaction" and obj.transaction_risk:
            tx = obj.transaction_risk.transaction
            return {
                "tx_hash": tx.tx_hash,
                "amount": _wei(tx.amount),            # wei строкой
                "gas_fee": _wei(tx.gas_fee),          # wei строкой
                "currency": tx.currency,
                "sender_address": tx.sender_wallet.address,
                "receiver_address": tx.receiver_wallet.address,
                "sender_label": tx.sender_wallet.label,
                "sender_label_source": tx.sender_wallet.label_source,
                "receiver_label": tx.receiver_wallet.label,
                "receiver_label_source": tx.receiver_wallet.label_source,
                "block_number": tx.block_number,
                "transaction_timestamp": tx.transaction_timestamp,
                "status": tx.status,
            }
        if obj.target_type == "wallet" and obj.wallet_risk:
            wr = obj.wallet_risk
            w = wr.wallet
            return {
                "address": w.address,
                "transaction_count": w.transaction_count,
                "total_received": _wei(w.total_received),  # wei строкой
                "total_sent": _wei(w.total_sent),          # wei строкой
                "risk_score": float(w.risk_score),
                "is_flagged": w.is_flagged,
                "label": w.label,
                "label_source": w.label_source,
                "first_seen_at": w.first_seen_at,
                "last_seen_at": w.last_seen_at,
                # Вклад ИИ и графа в эту оценку риска
                "rule_score": float(wr.rule_score),
                "ml_score": float(wr.ml_score),
                "ml_explanation": wr.ml_explanation,
                "graph_score": float(wr.graph_score) if wr.graph_score is not None else None,
                "graph_explanation": _graph_explanation(w),
            }
        return None


class StatusUpdateSerializer(serializers.Serializer):
    """Тело запроса PATCH /api/alerts/{id}/status/."""

    status = serializers.ChoiceField(choices=sorted(VALID_STATUSES))


class WalletSerializer(serializers.ModelSerializer):
    """Кошелёк для страницы «Кошельки». Суммы (wei) — строками, риск — числом."""

    total_received = serializers.SerializerMethodField()
    total_sent = serializers.SerializerMethodField()
    risk_score = serializers.SerializerMethodField()

    class Meta:
        model = Wallet
        fields = [
            "id", "address", "label", "label_source", "labeled_at",
            "transaction_count",
            "total_received", "total_sent", "risk_score", "is_flagged",
            "first_seen_at", "last_seen_at",
        ]

    def get_total_received(self, obj: Wallet) -> str:
        return _wei(obj.total_received)

    def get_total_sent(self, obj: Wallet) -> str:
        return _wei(obj.total_sent)

    def get_risk_score(self, obj: Wallet) -> float:
        return float(obj.risk_score)


class WalletFeaturesSerializer(serializers.ModelSerializer):
    """Признаки кошелька (wei-суммы — строками)."""

    total_received = serializers.SerializerMethodField()
    total_sent = serializers.SerializerMethodField()
    avg_amount = serializers.SerializerMethodField()
    max_amount = serializers.SerializerMethodField()

    class Meta:
        model = WalletFeatures
        exclude = ["wallet"]

    def get_total_received(self, o) -> str: return _wei(o.total_received)
    def get_total_sent(self, o) -> str: return _wei(o.total_sent)
    def get_avg_amount(self, o) -> str: return _wei(o.avg_amount)
    def get_max_amount(self, o) -> str: return _wei(o.max_amount)


class WalletGraphFeaturesSerializer(serializers.ModelSerializer):
    """Граф-признаки кошелька (положение в сети переводов). graph_score — числом."""

    graph_score = serializers.SerializerMethodField()

    class Meta:
        model = WalletGraphFeatures
        exclude = ["wallet"]

    def get_graph_score(self, o) -> float:
        return float(o.graph_score)


class WalletDetailSerializer(WalletSerializer):
    """Детали кошелька: поля списка + признаки + граф-признаки + последняя оценка риска."""

    features = serializers.SerializerMethodField()
    graph_features = serializers.SerializerMethodField()
    latest_risk = serializers.SerializerMethodField()

    class Meta(WalletSerializer.Meta):
        fields = WalletSerializer.Meta.fields + ["features", "graph_features", "latest_risk"]

    def get_features(self, obj: Wallet) -> dict | None:
        try:
            feats = obj.features
        except WalletFeatures.DoesNotExist:
            return None
        return WalletFeaturesSerializer(feats).data

    def get_graph_features(self, obj: Wallet) -> dict | None:
        try:
            gf = obj.graph_features
        except WalletGraphFeatures.DoesNotExist:
            return None
        return WalletGraphFeaturesSerializer(gf).data

    def get_latest_risk(self, obj: Wallet) -> dict | None:
        wr = obj.walletrisk_set.order_by("-created_at", "-id").first()
        if wr is None:
            return None
        return {
            "rule_score": float(wr.rule_score),
            "ml_score": float(wr.ml_score),
            "graph_score": float(wr.graph_score) if wr.graph_score is not None else None,
            "final_score": float(wr.final_score),
            "risk_level": wr.risk_level,
            "ml_explanation": wr.ml_explanation,
            "graph_explanation": _graph_explanation(obj),
            "decision": wr.decision,
        }


class TransactionSerializer(serializers.ModelSerializer):
    """Транзакция для страницы «Транзакции». amount (wei) — строкой."""

    amount = serializers.SerializerMethodField()
    gas_fee = serializers.SerializerMethodField()
    sender_address = serializers.CharField(source="sender_wallet.address", read_only=True)
    receiver_address = serializers.CharField(source="receiver_wallet.address", read_only=True)
    sender_label = serializers.CharField(source="sender_wallet.label", read_only=True, allow_null=True)
    receiver_label = serializers.CharField(source="receiver_wallet.label", read_only=True, allow_null=True)

    class Meta:
        model = Tx
        fields = [
            "id", "tx_hash", "sender_address", "receiver_address",
            "sender_label", "receiver_label",
            "amount", "gas_fee", "block_number", "transaction_timestamp",
            "status", "currency",
        ]

    def get_amount(self, obj: Tx) -> str:
        return _wei(obj.amount)

    def get_gas_fee(self, obj: Tx) -> str:
        return _wei(obj.gas_fee)


class RuleSerializer(serializers.ModelSerializer):
    """Правило Rule Engine. score — числом; is_active редактируется через PATCH."""

    score = serializers.SerializerMethodField()

    class Meta:
        model = Rule
        fields = ["id", "name", "description", "score", "is_active"]

    def get_score(self, obj: Rule) -> float:
        return float(obj.score)


class RuleToggleSerializer(serializers.Serializer):
    """Тело PATCH /api/rules/{id}/ — включить/выключить правило."""

    is_active = serializers.BooleanField()
