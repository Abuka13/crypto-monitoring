"""Корневая маршрутизация Django-проекта.

  /api/...        — REST API (см. alerts/urls.py)
  /api/schema/    — OpenAPI-схема (drf-spectacular)
  /api/docs/      — Swagger UI с описанием всех эндпоинтов
  /admin/         — стандартная админка (НЕ интерфейс аналитика, оставлена минимально)
"""
from django.contrib import admin
from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/", include("alerts.urls")),
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path(
        "api/docs/",
        SpectacularSwaggerView.as_view(url_name="schema"),
        name="swagger-ui",
    ),
]
