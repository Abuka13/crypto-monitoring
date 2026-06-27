"""Сериализаторы API.

Важно: денежные суммы (wei) отдаются СТРОКАМИ — большие числа не помещаются
в JS number и потеряли бы точность. Баллы риска (0..100) — числами, они малы.

Сработавшие правила берём из alert.description, как их формирует Rule Engine
(формат: «Сработавшие правила: Имя (+балл); Имя (+балл)»).
"""
from __future__ import annotations

import re
from decimal import Decimal

from rest_framework import serializers

from .models import Alert
from .transitions import VALID_STATUSES

# Префикс, которым Rule Engine начинает описание (collector/risk/engine.py).
_REASON_PREFIX = "Сработавшие правила:"
# «Имя правила (+12.34)». Имя может содержать свои скобки, напр. «Большая сумма (тест)»,
# поэтому якорим на «(+число)» — маркер балла, а не на любую скобку.
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

    class Meta:
        model = Alert
        fields = [
            "id", "target_type", "level", "status",
            "title", "description", "created_at", "resolved_at",
            "final_score", "risk_level", "fired_rules", "context",
        ]

    def get_final_score(self, obj: Alert) -> float | None:
        risk = _related_risk(obj)
        return float(risk.final_score) if risk else None

    def get_risk_level(self, obj: Alert) -> str | None:
        risk = _related_risk(obj)
        return risk.risk_level if risk else None

    def get_fired_rules(self, obj: Alert) -> list[dict]:
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
                "block_number": tx.block_number,
                "transaction_timestamp": tx.transaction_timestamp,
                "status": tx.status,
            }
        if obj.target_type == "wallet" and obj.wallet_risk:
            w = obj.wallet_risk.wallet
            return {
                "address": w.address,
                "transaction_count": w.transaction_count,
                "total_received": _wei(w.total_received),  # wei строкой
                "total_sent": _wei(w.total_sent),          # wei строкой
                "risk_score": float(w.risk_score),
                "is_flagged": w.is_flagged,
                "label": w.label,
                "first_seen_at": w.first_seen_at,
                "last_seen_at": w.last_seen_at,
            }
        return None


class StatusUpdateSerializer(serializers.Serializer):
    """Тело запроса PATCH /api/alerts/{id}/status/."""

    status = serializers.ChoiceField(choices=sorted(VALID_STATUSES))
