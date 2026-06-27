"""WSGI-точка входа для продакшен-серверов (gunicorn/uwsgi)."""
import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "monitoring_api.settings")
application = get_wsgi_application()
