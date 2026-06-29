"""Корневая маршрутизация Django-проекта.

  /api/...        — REST API (см. alerts/urls.py)
  /api/schema/    — OpenAPI-схема (drf-spectacular)
  /api/docs/      — Swagger UI с описанием всех эндпоинтов
  /admin/         — стандартная админка (НЕ интерфейс аналитика, оставлена минимально)
"""
from pathlib import Path

from django.contrib import admin
from django.http import FileResponse, Http404
from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView
from rest_framework.permissions import AllowAny

_FRONTEND_INDEX = Path(__file__).resolve().parent.parent / "frontend" / "index.html"


def spa_index(_request):
    """Отдать одностраничное приложение аналитика.

    Файл отдаётся как есть (FileResponse), без шаблонизатора Django — иначе
    конструкции вида {{...}} в JS были бы обработаны. SPA и API живут на одном
    источнике, поэтому фронтенд ходит на /api/... без проблем с CORS.
    """
    if not _FRONTEND_INDEX.exists():
        raise Http404("frontend/index.html не найден")
    return FileResponse(open(_FRONTEND_INDEX, "rb"), content_type="text/html; charset=utf-8")


urlpatterns = [
    path("", spa_index, name="spa"),
    path("admin/", admin.site.urls),
    path("api/", include("alerts.urls")),
    # Документация остаётся открытой (без токена), чтобы фронтенд-разработчики читали схему.
    path("api/schema/", SpectacularAPIView.as_view(permission_classes=[AllowAny]), name="schema"),
    path(
        "api/docs/",
        SpectacularSwaggerView.as_view(url_name="schema", permission_classes=[AllowAny]),
        name="swagger-ui",
    ),
]
