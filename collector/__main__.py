"""Позволяет запускать пакет как `python -m collector`."""
from .cli import main

if __name__ == "__main__":
    raise SystemExit(main())
