#!/usr/bin/env python
"""Точка входа Django (REST API для интерфейса аналитика, Шаг 5).

Отдельна от CLI сбора данных (python -m collector ...) — это разные процессы,
друг друга не затрагивают. Работает с той же базой PostgreSQL.
"""
import os
import sys


def main() -> None:
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "monitoring_api.settings")
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise ImportError(
            "Django не установлен. Выполни: python -m pip install -r requirements.txt"
        ) from exc
    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()
