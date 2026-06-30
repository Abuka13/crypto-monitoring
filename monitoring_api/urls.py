"""Корневая маршрутизация Django-проекта.

  /              — SPA аналитика (собранная сборка Vite из frontend/dist/)
  /assets/...    — статика сборки (JS/CSS с хешами)
  /api/...       — REST API (см. alerts/urls.py)
  /api/schema/   — OpenAPI-схема (drf-spectacular)
  /api/docs/     — Swagger UI с описанием всех эндпоинтов
  /admin/        — стандартная админка (для заведения пользователей-аналитиков)
"""
import mimetypes
from pathlib import Path

from django.contrib import admin
from django.http import FileResponse, Http404, HttpResponse
from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView
from rest_framework.permissions import AllowAny

# Фронтенд собирается командой `npm run build` в frontend/dist/.
_FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"
_DIST_DIR = _FRONTEND_DIR / "dist"
_DIST_INDEX = _DIST_DIR / "index.html"


def spa_index(_request):
    """Отдать собранное SPA (frontend/dist/index.html).

    Если сборки ещё нет — понятная подсказка, как её получить. SPA и API живут на
    одном источнике, поэтому фронтенд ходит на /api/... без проблем с CORS.
    """
    if not _DIST_INDEX.exists():
        return HttpResponse(
            "Сборка фронтенда не найдена. Выполни: cd frontend && npm install && npm run build "
            "(или запусти режим разработки: npm run dev на http://localhost:5173).",
            status=503, content_type="text/plain; charset=utf-8",
        )
    return FileResponse(open(_DIST_INDEX, "rb"), content_type="text/html; charset=utf-8")


def spa_asset(_request, path: str):
    """Отдать файл из frontend/dist/assets/ (JS/CSS сборки)."""
    target = (_DIST_DIR / "assets" / path).resolve()
    # Защита от выхода за пределы каталога assets.
    if not str(target).startswith(str((_DIST_DIR / "assets").resolve())) or not target.exists():
        raise Http404("asset не найден")
    ctype = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
    return FileResponse(open(target, "rb"), content_type=ctype)


urlpatterns = [
    path("", spa_index, name="spa"),
    path("assets/<path:path>", spa_asset, name="spa-asset"),
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
