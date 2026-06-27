"""Вьюхи REST API интерфейса аналитика (Шаг 5).

  GET   /api/alerts/                 — список (фильтры: status, level, target_type)
  GET   /api/alerts/{id}/            — детали + «почему сработало»
  PATCH /api/alerts/{id}/status/     — смена статуса (с проверкой переходов)
  GET   /api/stats/                  — сводка для дашборда
"""
from __future__ import annotations

from datetime import timedelta

from django.db.models import Count
from django.utils import timezone
from drf_spectacular.utils import (
    OpenApiExample, OpenApiParameter, OpenApiResponse, extend_schema,
)
from rest_framework import status as http_status
from rest_framework import viewsets
from rest_framework.decorators import action, api_view
from rest_framework.response import Response

from .models import Alert, Wallet
from .serializers import (
    AlertDetailSerializer, AlertListSerializer, StatusUpdateSerializer,
)
from .transitions import RESOLVING_STATUSES, validate_transition


@extend_schema(tags=["alerts"])
class AlertViewSet(viewsets.ReadOnlyModelViewSet):
    """Список и детали алертов (только чтение); смена статуса — отдельным action."""

    # select_related: одним запросом тянем связанные оценки риска и объекты,
    # чтобы не было N+1 при вычислении final_score и контекста.
    queryset = (
        Alert.objects.select_related(
            "transaction_risk__transaction__sender_wallet",
            "transaction_risk__transaction__receiver_wallet",
            "wallet_risk__wallet",
        )
        .all()
        .order_by("-created_at")  # свежие сверху
    )
    # Фильтры через query-параметры (?status=&level=&target_type=).
    filterset_fields = ["status", "level", "target_type"]
    ordering_fields = ["created_at", "level", "status"]
    ordering = ["-created_at"]

    def get_serializer_class(self):
        if self.action == "retrieve":
            return AlertDetailSerializer
        return AlertListSerializer

    @extend_schema(
        request=StatusUpdateSerializer,
        responses={200: AlertDetailSerializer},
        examples=[OpenApiExample("Взять в работу", value={"status": "in_progress"})],
        description=(
            "Сменить статус алерта. Разрешены переходы "
            "open → in_progress → closed/false_positive и откат in_progress → open. "
            "Недопустимый переход или значение — 400. При переходе в closed/"
            "false_positive проставляется resolved_at = now()."
        ),
    )
    @action(detail=True, methods=["patch"], url_path="status")
    def set_status(self, request, pk=None):
        alert = self.get_object()

        body = StatusUpdateSerializer(data=request.data)
        if not body.is_valid():
            return Response(
                {"detail": "Не передан корректный статус.", "errors": body.errors},
                status=http_status.HTTP_400_BAD_REQUEST,
            )
        new_status = body.validated_data["status"]

        error = validate_transition(alert.status, new_status)
        if error:
            return Response(
                {"detail": error},
                status=http_status.HTTP_400_BAD_REQUEST,
            )

        alert.status = new_status
        update_fields = ["status"]
        if new_status in RESOLVING_STATUSES:
            alert.resolved_at = timezone.now()
            update_fields.append("resolved_at")
        alert.save(update_fields=update_fields)

        return Response(AlertDetailSerializer(alert).data)


@extend_schema(
    tags=["stats"],
    responses=OpenApiResponse(
        description="Сводка для дашборда",
        examples=[
            OpenApiExample(
                "Пример",
                value={
                    "total_alerts": 40,
                    "alerts_last_24h": 6,
                    "by_status": {
                        "open": 30, "in_progress": 4,
                        "closed": 4, "false_positive": 2,
                    },
                    "by_level": {"low": 0, "medium": 0, "high": 40},
                    "flagged_wallets": 3,
                },
            )
        ],
    ),
)
@api_view(["GET"])
def stats_view(request):
    """Агрегаты для дашборда аналитика."""
    by_status = {"open": 0, "in_progress": 0, "closed": 0, "false_positive": 0}
    for row in Alert.objects.values("status").annotate(n=Count("id")):
        by_status[row["status"]] = row["n"]

    by_level = {"low": 0, "medium": 0, "high": 0}
    for row in Alert.objects.values("level").annotate(n=Count("id")):
        by_level[row["level"]] = row["n"]

    since = timezone.now() - timedelta(hours=24)
    return Response(
        {
            "total_alerts": Alert.objects.count(),
            "alerts_last_24h": Alert.objects.filter(created_at__gte=since).count(),
            "by_status": by_status,
            "by_level": by_level,
            "flagged_wallets": Wallet.objects.filter(is_flagged=True).count(),
        }
    )
