"""Настройки Django для REST API интерфейса аналитика.

Принципы:
- Подключаемся к УЖЕ существующей базе (db/schema.sql) через ту же DATABASE_URL.
- Наши 7 таблиц описаны моделями с managed=False — Django их не создаёт и не меняет.
- Служебные таблицы Django (миграции, сессии, auth) живут в той же базе, но
  наших таблиц не касаются.
"""
from __future__ import annotations

import os
from pathlib import Path

import dj_database_url
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent

# Та же конфигурация, что у CLI сбора данных (.env в корне проекта).
load_dotenv(BASE_DIR / ".env")

# --- Базовое ---
SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "dev-insecure-key-change-me")
DEBUG = os.getenv("DJANGO_DEBUG", "true").lower() == "true"
ALLOWED_HOSTS = os.getenv("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1").split(",")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # Сторонние
    "rest_framework",
    "corsheaders",
    "django_filters",
    "drf_spectacular",
    # Наше приложение
    "alerts",
]

MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",  # как можно выше, до CommonMiddleware
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "monitoring_api.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "monitoring_api.wsgi.application"

# --- База данных: та же, что у сбора данных ---
DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError(
        "Не задана DATABASE_URL. Скопируй .env.example в .env и впиши значение."
    )
DATABASES = {"default": dj_database_url.parse(DATABASE_URL)}

# --- DRF ---
REST_FRAMEWORK = {
    # Пагинация по умолчанию: limit/offset (?limit=&offset=).
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.LimitOffsetPagination",
    "PAGE_SIZE": 50,
    "DEFAULT_FILTER_BACKENDS": [
        "django_filters.rest_framework.DjangoFilterBackend",
        "rest_framework.filters.OrderingFilter",
    ],
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    # NUMERIC -> строка в JSON (это важно для wei: JS теряет точность на больших числах).
    "COERCE_DECIMAL_TO_STRING": True,
}

SPECTACULAR_SETTINGS = {
    "TITLE": "Crypto Monitoring API — интерфейс аналитика",
    "DESCRIPTION": (
        "REST API для Шага 5: список алертов, детали «почему сработало», "
        "смена статуса и сводка для дашборда. Все денежные суммы (wei) — строками."
    ),
    "VERSION": "1.0.0",
    "SERVE_INCLUDE_SCHEMA": False,
}

# --- CORS: на время разработки разрешаем локальный фронтенд на любом порту ---
CORS_ALLOWED_ORIGIN_REGEXES = [
    r"^http://localhost:\d+$",
    r"^http://127\.0\.0\.1:\d+$",
]
# Можно явно расширить список источников через .env (через запятую).
_extra_origins = os.getenv("CORS_ALLOWED_ORIGINS", "")
CORS_ALLOWED_ORIGINS = [o.strip() for o in _extra_origins.split(",") if o.strip()]

# --- Прочее ---
LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True
STATIC_URL = "static/"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
