"""Маршруты приложения alerts (префикс /api/ задаётся в monitoring_api/urls.py).

  /api/alerts/                 GET    список
  /api/alerts/{id}/            GET    детали
  /api/alerts/{id}/status/     PATCH  смена статуса
  /api/stats/                  GET    сводка
"""
from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import AlertViewSet, stats_view

router = DefaultRouter()
router.register("alerts", AlertViewSet, basename="alert")

urlpatterns = [
    path("stats/", stats_view, name="stats"),
    *router.urls,
]
