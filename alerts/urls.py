"""Маршруты приложения alerts (префикс /api/ задаётся в monitoring_api/urls.py).

  /api/alerts/                 GET    список
  /api/alerts/{id}/            GET    детали
  /api/alerts/{id}/status/     PATCH  смена статуса
  /api/wallets/                GET    кошельки
  /api/transactions/           GET    транзакции
  /api/rules/                  GET    правила
  /api/rules/{id}/             PATCH  вкл/выкл правило
  /api/stats/                  GET    сводка
  /api/auth/login/             POST   логин -> access + refresh
  /api/auth/refresh/           POST   обновить access по refresh
  /api/auth/me/                GET    текущий пользователь
  /api/auth/logout/            POST   отзыв refresh-токена
"""
from django.urls import path
from rest_framework.routers import DefaultRouter
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

from .views import (
    AlertViewSet, RuleViewSet, TransactionViewSet, WalletViewSet,
    logout_view, me_view, stats_view,
)

router = DefaultRouter()
router.register("alerts", AlertViewSet, basename="alert")
router.register("wallets", WalletViewSet, basename="wallet")
router.register("transactions", TransactionViewSet, basename="transaction")
router.register("rules", RuleViewSet, basename="rule")

urlpatterns = [
    path("stats/", stats_view, name="stats"),
    # Аутентификация (login/refresh открыты, me/logout — по токену)
    path("auth/login/", TokenObtainPairView.as_view(), name="login"),
    path("auth/refresh/", TokenRefreshView.as_view(), name="refresh"),
    path("auth/me/", me_view, name="me"),
    path("auth/logout/", logout_view, name="logout"),
    *router.urls,
]
