"""Маршруты /api/ (алерты, кошельки, транзакции, правила, stats, auth)."""
from django.urls import path
from rest_framework.routers import DefaultRouter
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

from .views import (
    AlertViewSet, RuleViewSet, TransactionViewSet, WalletViewSet,
    explain_alert_view, graph_view, logout_view, me_view,
    screen_history_view, screen_view, stats_view,
)

router = DefaultRouter()
router.register("alerts", AlertViewSet, basename="alert")
router.register("wallets", WalletViewSet, basename="wallet")
router.register("transactions", TransactionViewSet, basename="transaction")
router.register("rules", RuleViewSet, basename="rule")

urlpatterns = [
    path("stats/", stats_view, name="stats"),
    path("graph/", graph_view, name="graph"),
    path("alerts/<int:pk>/explain/", explain_alert_view, name="alert-explain"),
    path("screen/", screen_view, name="screen"),
    path("screen/history/", screen_history_view, name="screen-history"),
    # Аутентификация (login/refresh открыты, me/logout — по токену)
    path("auth/login/", TokenObtainPairView.as_view(), name="login"),
    path("auth/refresh/", TokenRefreshView.as_view(), name="refresh"),
    path("auth/me/", me_view, name="me"),
    path("auth/logout/", logout_view, name="logout"),
    *router.urls,
]
