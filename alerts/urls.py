"""Маршруты приложения alerts (префикс /api/ задаётся в monitoring_api/urls.py).

  /api/alerts/                 GET    список
  /api/alerts/{id}/            GET    детали
  /api/alerts/{id}/status/     PATCH  смена статуса
  /api/wallets/                GET    кошельки
  /api/transactions/           GET    транзакции
  /api/rules/                  GET    правила
  /api/rules/{id}/             PATCH  вкл/выкл правило
  /api/stats/                  GET    сводка
"""
from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import (
    AlertViewSet, RuleViewSet, TransactionViewSet, WalletViewSet, stats_view,
)

router = DefaultRouter()
router.register("alerts", AlertViewSet, basename="alert")
router.register("wallets", WalletViewSet, basename="wallet")
router.register("transactions", TransactionViewSet, basename="transaction")
router.register("rules", RuleViewSet, basename="rule")

urlpatterns = [
    path("stats/", stats_view, name="stats"),
    *router.urls,
]
