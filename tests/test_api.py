"""API интерфейса аналитика: доступ, валидация, фильтры и пагинация.

Скрининг ходит в Etherscan, поэтому в тестах он замокан целиком — проверяется
контракт эндпоинта, а не внешний сервис.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from django.db import connection

pytestmark = pytest.mark.django_db

T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)


# --------------------------------------------------------------------------
# Доступ: без токена всё закрыто
# --------------------------------------------------------------------------
@pytest.mark.parametrize("method,url", [
    ("get", "/api/alerts/"),
    ("get", "/api/wallets/"),
    ("get", "/api/transactions/"),
    ("get", "/api/rules/"),
    ("get", "/api/stats/"),
    ("get", "/api/graph/?address=0x" + "1" * 40),
    ("get", "/api/screen/history/"),
    ("post", "/api/screen/"),
    ("get", "/api/auth/me/"),
])
def test_endpoints_require_jwt(anon_client, method, url):
    resp = getattr(anon_client, method)(url)
    assert resp.status_code == 401, f"{url} доступен без токена"


def test_login_issues_token_and_grants_access(anon_client, db):
    from django.contrib.auth.models import User

    User.objects.create_user(username="ivan", password="secret-pass")
    r = anon_client.post("/api/auth/login/",
                         {"username": "ivan", "password": "secret-pass"}, format="json")
    assert r.status_code == 200 and "access" in r.json()

    anon_client.credentials(HTTP_AUTHORIZATION="Bearer " + r.json()["access"])
    assert anon_client.get("/api/auth/me/").status_code == 200


def test_login_rejects_bad_password(anon_client, db):
    from django.contrib.auth.models import User

    User.objects.create_user(username="ivan", password="secret-pass")
    r = anon_client.post("/api/auth/login/",
                         {"username": "ivan", "password": "wrong"}, format="json")
    assert r.status_code == 401


# --------------------------------------------------------------------------
# Скрининг: валидация адреса (Etherscan замокан)
# --------------------------------------------------------------------------
@pytest.mark.parametrize("bad", [
    "0x123", "не-адрес", "", "0xZZZZ427373d6d84e98730d7795d8f6f8731fdb79",
    "d8dA6BF26964aF9D7eEd9e03E53415D37aA96045",  # без 0x
    "0x" + "1" * 41,                              # слишком длинный
])
def test_screening_rejects_invalid_address(api_client, bad):
    r = api_client.post("/api/screen/", {"address": bad}, format="json")
    assert r.status_code == 400
    assert "формат" in r.json()["detail"].lower()


def test_screening_accepts_valid_address(api_client, monkeypatch):
    """Валидный адрес доходит до сервиса; сам сбор данных замокан."""
    address = "0x" + "a" * 40
    fake = {"address": address, "found": False, "no_activity": True,
            "risk_level": "LOW", "confidence": 0.9, "reasons": ["нет активности"],
            "sources": {}, "summary": {"tx_count": 0}, "tx_fetched": 0,
            "truncated": False, "collected": False, "cached": False, "elapsed_ms": 1}
    monkeypatch.setattr("collector.screening.screen_address",
                        lambda addr, cfg, force=False: fake)
    r = api_client.post("/api/screen/", {"address": address}, format="json")
    assert r.status_code == 200
    assert r.json()["risk_level"] == "LOW"


def test_screening_service_failure_is_503_not_500(api_client, monkeypatch):
    from collector.screening import ScreeningError

    def boom(addr, cfg, force=False):
        raise ScreeningError("Не удалось получить данные из Etherscan.")

    monkeypatch.setattr("collector.screening.screen_address", boom)
    r = api_client.post("/api/screen/", {"address": "0x" + "b" * 40}, format="json")
    assert r.status_code == 503
    assert "Etherscan" in r.json()["detail"]


def test_screening_history_is_empty_without_data(api_client):
    r = api_client.get("/api/screen/history/")
    assert r.status_code == 200 and r.json()["results"] == []


# --------------------------------------------------------------------------
# Списки: фильтры и пагинация
# --------------------------------------------------------------------------
@pytest.fixture
def alerts_dataset(db, make_wallet):
    """Набор алертов разных уровней и статусов для проверки фильтров."""
    rows = [
        ("critical", "open", "wallet"),
        ("high", "open", "wallet"),
        ("high", "closed", "transaction"),
        ("medium", "open", "wallet"),
        ("medium", "in_progress", "wallet"),
    ]
    ids = []
    for i, (level, status, target) in enumerate(rows):
        wallet_id = make_wallet()
        with connection.cursor() as cur:
            cur.execute(
                """INSERT INTO wallet_risk (wallet_id, rule_score, ml_score,
                       final_score, risk_level) VALUES (%s, 10, 0, 10, 'MEDIUM')
                   RETURNING id""", [wallet_id])
            risk_id = cur.fetchone()[0]
            cur.execute(
                """INSERT INTO alert (wallet_risk_id, target_type, wallet_id,
                       reason_key, title, description, level, status, created_at)
                   VALUES (%s, %s, %s, %s, %s, 'описание', %s, %s, %s) RETURNING id""",
                [risk_id, target, wallet_id, f"rule:R{i}", f"Алерт {i}",
                 level, status, T0 + timedelta(hours=i)])
            ids.append(cur.fetchone()[0])
    return ids


def test_alert_list_returns_all(api_client, alerts_dataset):
    body = api_client.get("/api/alerts/").json()
    assert body["count"] == 5
    assert len(body["results"]) == 5


@pytest.mark.parametrize("query,expected", [
    ("level=critical", 1),
    ("level=high", 2),
    ("status=open", 3),
    ("status=closed", 1),
    ("target_type=wallet", 4),
    ("target_type=transaction", 1),
    ("level=high&status=open", 1),
])
def test_alert_filters(api_client, alerts_dataset, query, expected):
    body = api_client.get(f"/api/alerts/?{query}").json()
    assert body["count"] == expected


def test_alert_search_by_title(api_client, alerts_dataset):
    body = api_client.get("/api/alerts/?search=Алерт 2").json()
    assert body["count"] == 1


def test_alert_pagination(api_client, alerts_dataset):
    first = api_client.get("/api/alerts/?limit=2").json()
    assert first["count"] == 5 and len(first["results"]) == 2
    assert first["next"] is not None

    second = api_client.get("/api/alerts/?limit=2&offset=2").json()
    assert len(second["results"]) == 2
    ids_first = {a["id"] for a in first["results"]}
    ids_second = {a["id"] for a in second["results"]}
    assert not (ids_first & ids_second), "страницы не должны пересекаться"

    last = api_client.get("/api/alerts/?limit=2&offset=4").json()
    assert len(last["results"]) == 1 and last["next"] is None


def test_alert_detail_carries_decision_and_evidence(api_client, alerts_dataset):
    body = api_client.get(f"/api/alerts/{alerts_dataset[0]}/").json()
    for key in ("risk_level", "fired_rules", "context", "decision", "evidence"):
        assert key in body


def test_alert_status_transition_and_validation(api_client, alerts_dataset):
    alert_id = alerts_dataset[0]  # open
    ok = api_client.patch(f"/api/alerts/{alert_id}/status/",
                          {"status": "in_progress"}, format="json")
    assert ok.status_code == 200 and ok.json()["status"] == "in_progress"

    bad = api_client.patch(f"/api/alerts/{alert_id}/status/",
                           {"status": "нет-такого"}, format="json")
    assert bad.status_code == 400


@pytest.fixture
def wallets_dataset(db, make_wallet):
    from django.db import connection as conn

    ids = []
    for i, (risk, flagged, label) in enumerate([
        (90.0, True, "mixer"), (55.0, True, None), (10.0, False, "exchange"),
    ]):
        wallet_id = make_wallet(label=label, tx_count=i + 1)
        with conn.cursor() as cur:
            cur.execute("UPDATE wallet SET risk_score=%s, is_flagged=%s WHERE id=%s",
                        [risk, flagged, wallet_id])
        ids.append(wallet_id)
    return ids


@pytest.mark.parametrize("query,expected", [
    ("", 3),
    ("is_flagged=true", 2),
    ("label=mixer", 1),
    ("risk=high", 1),      # >= 70
    ("risk=medium", 1),    # 40..70
    ("risk=low", 1),       # < 40
])
def test_wallet_filters(api_client, wallets_dataset, query, expected):
    body = api_client.get(f"/api/wallets/?{query}").json()
    assert body["count"] == expected


def test_wallet_amounts_are_strings(api_client, wallets_dataset):
    """wei отдаются строкой — иначе JS теряет точность."""
    body = api_client.get("/api/wallets/?limit=1").json()
    row = body["results"][0]
    assert isinstance(row["total_received"], str)
    assert isinstance(row["total_sent"], str)


def test_transaction_list_and_search(api_client, make_wallet, make_tx):
    a, b = make_wallet(), make_wallet()
    make_tx(a, b, amount_wei=3 * 10**18)
    body = api_client.get("/api/transactions/").json()
    assert body["count"] == 1
    assert isinstance(body["results"][0]["amount"], str)


def test_stats_shape(api_client, alerts_dataset):
    body = api_client.get("/api/stats/").json()
    for key in ("total_alerts", "by_status", "by_level", "flagged_wallets", "trend"):
        assert key in body
    assert body["total_alerts"] == 5
    assert body["by_level"]["critical"] == 1
    assert len(body["trend"]) == 14


def test_rules_are_listed_from_seed(api_client):
    """Справочник правил приходит из стартовых данных схемы."""
    body = api_client.get("/api/rules/").json()
    names = {r["name"] for r in body}
    assert "Связь с миксером" in names and "Санкционный адрес" in names


def test_graph_endpoint_validates_center(api_client):
    assert api_client.get("/api/graph/").status_code == 404
    assert api_client.get("/api/graph/?address=0x" + "9" * 40).status_code == 404


def test_graph_returns_ego_network(api_client, make_wallet, make_tx):
    centre = make_wallet("0x" + "c" * 40)
    other = make_wallet()
    make_tx(centre, other, amount_wei=2 * 10**18)

    body = api_client.get(f"/api/graph/?address=0x{'c' * 40}&depth=1").json()
    assert body["center_id"] == centre
    assert {n["id"] for n in body["nodes"]} == {centre, other}
    assert len(body["edges"]) == 1
    assert isinstance(body["edges"][0]["total_amount"], str)


@pytest.mark.parametrize("query,field,expected", [
    ("depth=9", "depth", 2),        # ограничивается сверху
    ("limit=99999", "limit", 200),
    ("depth=abc", "depth", 1),      # мусор -> значение по умолчанию
])
def test_graph_params_are_clamped(api_client, make_wallet, query, field, expected):
    make_wallet("0x" + "d" * 40)
    body = api_client.get(f"/api/graph/?address=0x{'d' * 40}&{query}").json()
    assert body[field] == expected
