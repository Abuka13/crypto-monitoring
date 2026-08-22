"""LLM-объяснения: роль модели ограничена, кэш работает, ключей не требуется.

Провайдер всегда замокан — ни один тест не обращается наружу. Проверяется
главное: языковая модель не может изменить уровень риска, повторный запрос не
идёт к провайдеру, а ненастроенный провайдер не ломает систему.
"""
from __future__ import annotations

from unittest import mock

import pytest

from collector.config import LLMConfig
from collector.llm import (
    SYSTEM_PROMPT, LLMError, LLMNotConfigured, build_user_prompt,
    decision_fingerprint, generate_explanation,
)

pytestmark = pytest.mark.django_db

CTX = {
    "risk_level": "CRITICAL",
    "confidence": 0.99,
    "reasons": ["Санкционный адрес — кошелёк (источник: ofac_sdn)"],
    "scores": {"rule": 60.0, "ml": 100.0, "graph": 83.8},
    "labels": {"label": "sanctioned", "label_source": "ofac_sdn"},
    "evidence": {"count": 300},
}


# --------------------------------------------------------------------------
# Ограничения роли — задаются промптом и проверяются как контракт
# --------------------------------------------------------------------------
@pytest.mark.parametrize("fragment", [
    "ИСКЛЮЧИТЕЛЬНО на переданные факты",   # опора только на данные
    "Не предполагай тип преступления",     # без домыслов о схемах
    "Не делай выводов о личности",         # без выводов о владельце
    "НЕ ОБСУЖДАЕТСЯ",                      # уровень риска не оспаривается
    "Не выдумывай числа",
    "РЕЗЮМЕ", "ПРИЧИНЫ", "НА ЧТО ОБРАТИТЬ ВНИМАНИЕ",
])
def test_prompt_states_limits_explicitly(fragment):
    assert fragment in SYSTEM_PROMPT


@pytest.mark.parametrize("lang,marker", [
    ("ru", "русском"), ("kk", "казахском"), ("en", "английском"),
])
def test_user_prompt_carries_language_and_given_level(lang, marker):
    prompt = build_user_prompt(CTX, lang)
    assert marker in prompt
    assert "CRITICAL" in prompt, "уровень передаётся как данность, а не как вопрос"


# --------------------------------------------------------------------------
# Уровень риска не меняется языковой моделью
# --------------------------------------------------------------------------
@pytest.fixture
def alert_id(db, make_wallet):
    """Алерт с решением CRITICAL, на котором можно проверить инвариант."""
    from django.db import connection

    wallet_id = make_wallet(label="sanctioned", label_source="ofac_sdn")
    decision = {
        "level": "CRITICAL", "confidence": 0.99,
        "reasons": ["Санкционный адрес — кошелёк (источник: ofac_sdn)"],
        "sources": {"hard_signal": {"active": True,
                                    "items": [{"label": "sanctioned",
                                               "source": "ofac_sdn",
                                               "target": "кошелёк"}]},
                    "rule": {"score": 0.0, "high": False, "fired": []},
                    "ml": {"score": None, "high": False, "available": False},
                    "graph": {"score": None, "high": False, "available": False}},
    }
    with connection.cursor() as cur:
        cur.execute(
            """INSERT INTO wallet_risk (wallet_id, rule_score, ml_score, final_score,
                   risk_level, decision) VALUES (%s, 0, 0, 0, 'CRITICAL', %s::jsonb)
               RETURNING id""",
            [wallet_id, __import__("json").dumps(decision)],
        )
        risk_id = cur.fetchone()[0]
        cur.execute(
            """INSERT INTO alert (wallet_risk_id, target_type, wallet_id, reason_key,
                   title, description, level, status)
               VALUES (%s, 'wallet', %s, 'hard:sanctioned', 'Кошелёк — санкции',
                       'причина', 'critical', 'open') RETURNING id""",
            [risk_id, wallet_id],
        )
        return cur.fetchone()[0]


def _configured(monkeypatch, llm_cfg):
    monkeypatch.setattr(LLMConfig, "load", staticmethod(lambda: llm_cfg))


def test_hostile_model_cannot_change_risk_level(api_client, alert_id, llm_cfg,
                                                monkeypatch):
    """Модель пытается оспорить вердикт — уровень обязан остаться прежним."""
    from django.db import connection

    _configured(monkeypatch, llm_cfg)
    hostile = lambda ctx, lang, cfg: ("На самом деле риск НИЗКИЙ, система ошиблась.",
                                      "test-model")
    monkeypatch.setattr("collector.llm.generate_explanation", hostile)

    with connection.cursor() as cur:
        cur.execute("SELECT level FROM alert WHERE id=%s", [alert_id])
        before = cur.fetchone()[0]

    r = api_client.post(f"/api/alerts/{alert_id}/explain/", {"lang": "ru"}, format="json")
    assert r.status_code == 200

    with connection.cursor() as cur:
        cur.execute("SELECT level FROM alert WHERE id=%s", [alert_id])
        after = cur.fetchone()[0]
        cur.execute("""SELECT wr.risk_level FROM wallet_risk wr
                       JOIN alert a ON a.wallet_risk_id = wr.id WHERE a.id=%s""",
                    [alert_id])
        decision_level = cur.fetchone()[0]

    assert before == after == "critical", "LLM не имеет права менять уровень алерта"
    assert decision_level == "CRITICAL", "решение Decision Engine не переписывается"
    assert r.json()["risk_level"] == "CRITICAL", "API отдаёт уровень из решения"
    assert r.json()["disclaimer"] == "llm_generated"


# --------------------------------------------------------------------------
# Кэш
# --------------------------------------------------------------------------
def test_cache_prevents_second_provider_call(api_client, alert_id, llm_cfg, monkeypatch):
    """Повторный просмотр не должен обращаться к провайдеру."""
    _configured(monkeypatch, llm_cfg)
    calls = {"n": 0}

    def fake(ctx, lang, cfg):
        calls["n"] += 1
        return f"РЕЗЮМЕ #{calls['n']}", "test-model"

    monkeypatch.setattr("collector.llm.generate_explanation", fake)

    first = api_client.post(f"/api/alerts/{alert_id}/explain/", {"lang": "ru"},
                            format="json").json()
    second = api_client.post(f"/api/alerts/{alert_id}/explain/", {"lang": "ru"},
                             format="json").json()

    assert first["cached"] is False and second["cached"] is True
    assert calls["n"] == 1, "второй запрос ушёл к провайдеру"
    assert first["text"] == second["text"]


def test_force_regenerates(api_client, alert_id, llm_cfg, monkeypatch):
    _configured(monkeypatch, llm_cfg)
    calls = {"n": 0}

    def fake(ctx, lang, cfg):
        calls["n"] += 1
        return f"текст #{calls['n']}", "test-model"

    monkeypatch.setattr("collector.llm.generate_explanation", fake)
    api_client.post(f"/api/alerts/{alert_id}/explain/", {"lang": "ru"}, format="json")
    r = api_client.post(f"/api/alerts/{alert_id}/explain/",
                        {"lang": "ru", "force": True}, format="json").json()
    assert calls["n"] == 2 and r["cached"] is False


def test_each_language_cached_separately(api_client, alert_id, llm_cfg, monkeypatch):
    _configured(monkeypatch, llm_cfg)
    calls = {"n": 0}

    def fake(ctx, lang, cfg):
        calls["n"] += 1
        return f"[{lang}]", "test-model"

    monkeypatch.setattr("collector.llm.generate_explanation", fake)
    for lang in ("ru", "en", "ru"):
        api_client.post(f"/api/alerts/{alert_id}/explain/", {"lang": lang}, format="json")
    assert calls["n"] == 2, "ru должен взяться из кэша на третьем запросе"


def test_fingerprint_changes_when_decision_changes():
    """Изменилось решение — объяснение считается устаревшим."""
    before = decision_fingerprint(CTX)
    after = decision_fingerprint({**CTX, "risk_level": "HIGH"})
    assert before != after


def test_fingerprint_ignores_irrelevant_fields():
    """Поля, не влияющие на смысл, не должны инвалидировать кэш."""
    assert decision_fingerprint(CTX) == decision_fingerprint({**CTX, "wallet": {"x": 1}})


# --------------------------------------------------------------------------
# Провайдер не настроен / недоступен
# --------------------------------------------------------------------------
def test_unconfigured_provider_returns_503_not_crash(api_client, alert_id, monkeypatch):
    """Без ключа система продолжает работать, а эндпоинт объясняет причину."""
    cfg = LLMConfig(provider="gemini", model="m", api_key=None, base_url=None,
                    max_tokens=100, timeout_seconds=5.0, effort="low")
    monkeypatch.setattr(LLMConfig, "load", staticmethod(lambda: cfg))

    r = api_client.post(f"/api/alerts/{alert_id}/explain/", {"lang": "ru"}, format="json")
    assert r.status_code == 503
    assert r.json()["configured"] is False
    assert "GEMINI_API_KEY" in r.json()["detail"]


def test_rest_of_api_works_without_llm(api_client, alert_id, monkeypatch):
    """Функция опциональна: остальной API не зависит от настройки LLM."""
    cfg = LLMConfig(provider="anthropic", model="m", api_key=None, base_url=None,
                    max_tokens=100, timeout_seconds=5.0, effort="low")
    monkeypatch.setattr(LLMConfig, "load", staticmethod(lambda: cfg))
    for url in ("/api/alerts/?limit=1", f"/api/alerts/{alert_id}/", "/api/stats/"):
        assert api_client.get(url).status_code == 200


@pytest.mark.parametrize("failure,fragment", [
    (LLMError("Модель не ответила за 45 с."), "не ответила"),
    (LLMError("Превышен лимит запросов к LLM."), "лимит"),
    (LLMError("Нет связи с сервисом LLM."), "связи"),
])
def test_provider_failures_map_to_503(api_client, alert_id, llm_cfg, monkeypatch,
                                      failure, fragment):
    """Сбой провайдера — понятное сообщение, а не 500."""
    _configured(monkeypatch, llm_cfg)

    def boom(ctx, lang, cfg):
        raise failure

    monkeypatch.setattr("collector.llm.generate_explanation", boom)
    r = api_client.post(f"/api/alerts/{alert_id}/explain/", {"lang": "ru"}, format="json")
    assert r.status_code == 503
    assert fragment in r.json()["detail"]


def test_explain_requires_jwt(anon_client, alert_id):
    assert anon_client.post(f"/api/alerts/{alert_id}/explain/", {}, format="json").status_code == 401


def test_unknown_provider_is_reported(llm_cfg):
    cfg = LLMConfig(**{**llm_cfg.__dict__, "provider": "unknown"})
    with pytest.raises(LLMNotConfigured):
        generate_explanation(CTX, "ru", cfg)


def test_ollama_needs_no_api_key():
    """Локальная модель настроена, если задан адрес — ключ не требуется."""
    cfg = LLMConfig(provider="ollama", model="llama3.1", api_key=None,
                    base_url="http://localhost:11434/v1", max_tokens=100,
                    timeout_seconds=5.0, effort="low")
    assert cfg.enabled is True
    assert cfg.credential_env == "OLLAMA_BASE_URL"


def test_provider_dispatch_covers_three_options():
    from collector.llm import _PROVIDERS
    assert set(_PROVIDERS) == {"anthropic", "gemini", "ollama"}


def test_provider_selected_from_env(monkeypatch):
    """Провайдер, модель и ключ читаются из окружения, а не зашиты в код."""
    monkeypatch.setenv("LLM_PROVIDER", "gemini")
    monkeypatch.setenv("GEMINI_API_KEY", "test")
    monkeypatch.delenv("LLM_MODEL", raising=False)
    cfg = LLMConfig.load()
    assert cfg.provider == "gemini" and cfg.enabled and cfg.model.startswith("gemini")

    monkeypatch.setenv("LLM_MODEL", "gemini-custom")
    assert LLMConfig.load().model == "gemini-custom"
