"""Страховка: тесты не ходят наружу и не требуют внешних ключей.

Если кто-то добавит тест, забыв замокать Etherscan или LLM-провайдера, он
упадёт здесь — а не отправит настоящий запрос из CI.
"""
from __future__ import annotations

import os

import pytest
import requests

from tests.conftest import NetworkAccessDenied


def test_outbound_network_is_blocked():
    """Обращение к внешнему хосту в тестах запрещено."""
    with pytest.raises(NetworkAccessDenied):
        requests.get("https://api.etherscan.io/api", timeout=1)


def test_llm_provider_call_is_blocked_too():
    with pytest.raises(NetworkAccessDenied):
        requests.post("https://generativelanguage.googleapis.com/v1beta/models/x",
                      json={}, timeout=1)


def test_localhost_still_allowed(db):
    """База данных на localhost должна оставаться доступной."""
    from django.db import connection

    with connection.cursor() as cur:
        cur.execute("SELECT 1")
        assert cur.fetchone()[0] == 1


@pytest.mark.parametrize("key", ["ETHERSCAN_API_KEY", "ANTHROPIC_API_KEY",
                                 "GEMINI_API_KEY"])
def test_suite_does_not_depend_on_external_keys(key, monkeypatch, api_client):
    """Ключей внешних сервисов быть не должно — API работает и без них."""
    monkeypatch.delenv(key, raising=False)
    assert api_client.get("/api/alerts/").status_code == 200
    assert api_client.get("/api/stats/").status_code == 200


def test_llm_config_loads_without_any_key(monkeypatch):
    """LLMConfig читается без ключей и просто сообщает, что не настроен."""
    from collector.config import LLMConfig

    for key in ("ANTHROPIC_API_KEY", "GEMINI_API_KEY", "LLM_PROVIDER", "LLM_MODEL"):
        monkeypatch.delenv(key, raising=False)
    cfg = LLMConfig.load()
    assert cfg.enabled is False
    assert cfg.credential_env == "ANTHROPIC_API_KEY"
