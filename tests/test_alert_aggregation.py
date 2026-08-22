"""Агрегация алертов: сущность + причина, а не транзакция.

До этой модели одна находка порождала сотни сигналов (300 переводов с санкционным
адресом = 300 CRITICAL). Тесты фиксируют новое поведение: один активный алерт на
связку (кошелёк, причина), повторные события идут в доказательства, разные
причины остаются разными алертами, а закрытый алерт не воскресает.
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest
from django.db import connection

from collector.risk import engine
from collector.risk.decision import Decision, RiskSources, decide

MIXER = "Связь с миксером"
pytestmark = pytest.mark.django_db


# --------------------------------------------------------------------------
# Ключ причины
# --------------------------------------------------------------------------
def test_hard_signal_dominates_reason_key(decision_cfg):
    """Hard Signal задаёт тождество находки: «крупные» переводы её не дробят."""
    plain = decide(RiskSources(hard_signals=[("sanctioned", "ofac_sdn", "кошелёк")]),
                   decision_cfg)
    also_large = decide(
        RiskSources(hard_signals=[("sanctioned", "ofac_sdn", "кошелёк")],
                    rule_score=30.0, fired_rules=[("Большая сумма", 30.0)]),
        decision_cfg)
    key_a = engine.reason_key(plain.sources, decision_cfg)
    key_b = engine.reason_key(also_large.sources, decision_cfg)
    assert key_a == key_b == "hard:sanctioned"


def test_strong_rule_dominates_over_ordinary(decision_cfg):
    src = decide(RiskSources(rule_score=70.0,
                             fired_rules=[(MIXER, 40.0), ("Большая сумма", 30.0)]),
                 decision_cfg)
    assert engine.reason_key(src.sources, decision_cfg) == f"rule:{MIXER}"


def test_different_causes_give_different_keys(decision_cfg):
    """Санкции и дробление не должны сливаться в один алерт."""
    sanctions = decide(RiskSources(hard_signals=[("sanctioned", "ofac_sdn", "кошелёк")]),
                       decision_cfg)
    structuring = decide(RiskSources(rule_score=35.0,
                                     fired_rules=[("Дробление сумм", 35.0)]), decision_cfg)
    assert (engine.reason_key(sanctions.sources, decision_cfg)
            != engine.reason_key(structuring.sources, decision_cfg))


def test_ml_and_graph_not_in_reason_key(decision_cfg):
    """ML и граф колеблются от прогона к прогону — в ключ они не входят."""
    a = decide(RiskSources(rule_score=40.0, fired_rules=[(MIXER, 40.0)],
                           ml_score=10.0), decision_cfg)
    b = decide(RiskSources(rule_score=40.0, fired_rules=[(MIXER, 40.0)],
                           ml_score=95.0, graph_score=80.0), decision_cfg)
    assert engine.reason_key(a.sources, decision_cfg) == engine.reason_key(b.sources, decision_cfg)


# --------------------------------------------------------------------------
# Дедупликация и доказательства (нужна реальная запись в БД)
# --------------------------------------------------------------------------
class _Conn:
    """Адаптер, дающий движку psycopg2-подобный интерфейс поверх Django.

    Движок ходит в БД через conn.cursor()/conn.commit(); в тестах нам нужно то же
    самое соединение, что и у Django, иначе данные окажутся в разных транзакциях.
    """

    def cursor(self):
        return connection.cursor()

    def commit(self):
        pass  # транзакцией управляет pytest-django

    def rollback(self):
        pass


@pytest.fixture
def conn():
    return _Conn()


@pytest.fixture
def risk_row(db, make_wallet):
    """Кошелёк + строка wallet_risk, на которую можно сослаться из алерта."""
    def _make(**kw):
        wallet_id = make_wallet(**kw)
        with connection.cursor() as cur:
            cur.execute(
                """INSERT INTO wallet_risk (wallet_id, rule_score, ml_score,
                       final_score, risk_level) VALUES (%s, 40, 0, 40, 'MEDIUM')
                   RETURNING id""",
                [wallet_id],
            )
            return wallet_id, cur.fetchone()[0]
    return _make


@pytest.fixture
def tx_risk_row(db):
    """Строка transaction_risk — нужна для алертов с target_type='transaction'."""
    def _make(tx_id: int) -> int:
        with connection.cursor() as cur:
            cur.execute(
                """INSERT INTO transaction_risk (transaction_id, rule_score, ml_score,
                       final_score, risk_level) VALUES (%s, 40, 0, 40, 'MEDIUM')
                   RETURNING id""",
                [tx_id],
            )
            return cur.fetchone()[0]
    return _make


def _emit(conn, wallet_id, risk_id, address, reason, level="high", tx_id=None):
    """Алерт уровня кошелька; tx_id (если есть) добавляется в доказательства.

    target_type и risk_id должны быть согласованы — CHECK и внешние ключи в схеме
    следят за этим, поэтому здесь всегда wallet_risk_id.
    """
    return engine._emit_entity_alert(
        conn, wallet_id=wallet_id, address=address, reason=reason,
        target_type="wallet", risk_id=risk_id,
        description="причина", level=level, evidence_tx_id=tx_id,
    )


def test_same_wallet_same_reason_is_one_alert(conn, risk_row, make_tx):
    """Повторное событие с той же причиной обновляет алерт, а не плодит новый."""
    wallet_id, risk_id = risk_row(address="0xaaa1")
    other = risk_row(address="0xbbb1")[0]
    tx1 = make_tx(other, wallet_id)
    tx2 = make_tx(other, wallet_id)

    assert _emit(conn, wallet_id, risk_id, "0xaaa1", "hard:sanctioned", tx_id=tx1) == "created"
    assert _emit(conn, wallet_id, risk_id, "0xaaa1", "hard:sanctioned", tx_id=tx2) == "updated"

    with connection.cursor() as cur:
        cur.execute("SELECT count(*) FROM alert WHERE wallet_id=%s", [wallet_id])
        assert cur.fetchone()[0] == 1
        cur.execute("SELECT evidence_count FROM alert WHERE wallet_id=%s", [wallet_id])
        assert cur.fetchone()[0] == 2, "обе транзакции должны стать доказательствами"


def test_repeat_scoring_does_not_duplicate_evidence(conn, risk_row, make_tx):
    """Повторный расчёт по тем же данным не задваивает доказательства."""
    wallet_id, risk_id = risk_row(address="0xaaa2")
    other = risk_row(address="0xbbb2")[0]
    tx = make_tx(other, wallet_id)

    for _ in range(3):
        _emit(conn, wallet_id, risk_id, "0xaaa2", "hard:sanctioned", tx_id=tx)

    with connection.cursor() as cur:
        cur.execute("SELECT count(*) FROM alert WHERE wallet_id=%s", [wallet_id])
        assert cur.fetchone()[0] == 1
        cur.execute("SELECT evidence_count FROM alert WHERE wallet_id=%s", [wallet_id])
        assert cur.fetchone()[0] == 1
        cur.execute("SELECT count(*) FROM alert_evidence")
        assert cur.fetchone()[0] == 1


def test_different_reasons_give_separate_alerts(conn, risk_row):
    """Разные причины по одному кошельку — разные алерты."""
    wallet_id, risk_id = risk_row(address="0xaaa3")
    _emit(conn, wallet_id, risk_id, "0xaaa3", "hard:sanctioned")
    _emit(conn, wallet_id, risk_id, "0xaaa3", "rule:Дробление сумм")

    with connection.cursor() as cur:
        cur.execute("SELECT reason_key FROM alert WHERE wallet_id=%s ORDER BY reason_key",
                    [wallet_id])
        assert [r[0] for r in cur.fetchall()] == ["hard:sanctioned", "rule:Дробление сумм"]


def test_closed_alert_is_not_resurrected(conn, risk_row):
    """Разобранный аналитиком алерт не воскресает: новое событие заводит новый."""
    wallet_id, risk_id = risk_row(address="0xaaa4")
    _emit(conn, wallet_id, risk_id, "0xaaa4", "hard:sanctioned")

    with connection.cursor() as cur:
        cur.execute("UPDATE alert SET status='closed', resolved_at=now() "
                    "WHERE wallet_id=%s", [wallet_id])

    from collector import db as cdb
    assert cdb.find_active_entity_alert(conn, wallet_id, "hard:sanctioned") is None

    assert _emit(conn, wallet_id, risk_id, "0xaaa4", "hard:sanctioned") == "created"
    with connection.cursor() as cur:
        cur.execute("SELECT count(*) FROM alert WHERE wallet_id=%s", [wallet_id])
        assert cur.fetchone()[0] == 2, "старый закрыт, новый заведён"


def test_alert_level_only_rises(conn, risk_row):
    """Повторное более слабое событие не занижает уже поднятую находку."""
    wallet_id, risk_id = risk_row(address="0xaaa5")
    _emit(conn, wallet_id, risk_id, "0xaaa5", "hard:sanctioned", level="critical")
    _emit(conn, wallet_id, risk_id, "0xaaa5", "hard:sanctioned", level="medium")

    with connection.cursor() as cur:
        cur.execute("SELECT level FROM alert WHERE wallet_id=%s", [wallet_id])
        assert cur.fetchone()[0] == "critical"


def test_unique_index_blocks_duplicate_active_alerts(conn, risk_row):
    """Уникальность гарантирует БД, а не только код движка."""
    from django.db import IntegrityError, transaction

    wallet_id, risk_id = risk_row(address="0xaaa6")
    _emit(conn, wallet_id, risk_id, "0xaaa6", "hard:sanctioned")

    with pytest.raises(IntegrityError):
        with transaction.atomic(), connection.cursor() as cur:
            cur.execute(
                """INSERT INTO alert (wallet_risk_id, target_type, wallet_id, reason_key,
                       title, level, status)
                   VALUES (%s, 'wallet', %s, 'hard:sanctioned', 'дубль', 'high', 'open')""",
                [risk_id, wallet_id],
            )


def test_evidence_summary_is_recalculated(conn, risk_row, make_tx):
    """Сводка доказательств (число, период, объём) считается по фактическим tx."""
    wallet_id, risk_id = risk_row(address="0xaaa7")
    other = risk_row(address="0xbbb7")[0]
    first = datetime(2026, 1, 1, tzinfo=timezone.utc)
    last = datetime(2026, 3, 1, tzinfo=timezone.utc)
    tx1 = make_tx(other, wallet_id, amount_wei=2 * 10**18, when=first)
    tx2 = make_tx(other, wallet_id, amount_wei=3 * 10**18, when=last)

    _emit(conn, wallet_id, risk_id, "0xaaa7", "hard:sanctioned", tx_id=tx1)
    _emit(conn, wallet_id, risk_id, "0xaaa7", "hard:sanctioned", tx_id=tx2)

    with connection.cursor() as cur:
        cur.execute("""SELECT evidence_count, first_event_at, last_event_at, total_amount
                       FROM alert WHERE wallet_id=%s""", [wallet_id])
        count, got_first, got_last, total = cur.fetchone()
    assert count == 2
    assert got_first == first and got_last == last
    assert total == Decimal(5 * 10**18)


def test_wallet_alert_gets_wallet_transactions_as_evidence(conn, risk_row, make_tx):
    """Для алерта уровня кошелька доказательства — операции этого кошелька."""
    wallet_id, risk_id = risk_row(address="0xaaa8")
    other = risk_row(address="0xbbb8")[0]
    make_tx(other, wallet_id)
    make_tx(wallet_id, other)

    engine._emit_entity_alert(
        conn, wallet_id=wallet_id, address="0xaaa8", reason="rule:Высокая частота",
        target_type="wallet", risk_id=risk_id, description="…", level="medium",
        evidence_wallet_id=wallet_id,
    )
    with connection.cursor() as cur:
        cur.execute("SELECT evidence_count FROM alert WHERE wallet_id=%s", [wallet_id])
        assert cur.fetchone()[0] == 2


def test_transaction_triggered_alert_is_kept_on_the_entity(conn, risk_row, make_tx,
                                                           tx_risk_row):
    """Срабатывание по транзакции заводит алерт на КОШЕЛЬКЕ, а не на переводе.

    Именно это схлопывает сотни переводов с одним санкционным адресом в один
    сигнал: сущность одна, транзакции идут в доказательства.
    """
    subject = risk_row(address="0xaaa9")[0]
    other = risk_row(address="0xbbb9")[0]
    tx_ids = [make_tx(other, subject) for _ in range(3)]

    for tx_id in tx_ids:
        engine._emit_entity_alert(
            conn, wallet_id=subject, address="0xaaa9", reason="hard:sanctioned",
            target_type="transaction", risk_id=tx_risk_row(tx_id),
            description="Санкционный адрес", level="critical", evidence_tx_id=tx_id,
        )

    with connection.cursor() as cur:
        cur.execute("SELECT count(*) FROM alert WHERE wallet_id=%s", [subject])
        assert cur.fetchone()[0] == 1, "3 транзакции -> 1 алерт на сущность"
        cur.execute("SELECT evidence_count, target_type FROM alert WHERE wallet_id=%s",
                    [subject])
        count, target_type = cur.fetchone()
    assert count == 3 and target_type == "transaction"


def test_subject_is_the_labelled_participant(decision_cfg):
    """Сущность находки — участник с триггерящей меткой, иначе отправитель."""
    sender, receiver = 10, 20
    assert engine._subject_wallet(sender, receiver, None, "sanctioned",
                                  decision_cfg) == receiver
    assert engine._subject_wallet(sender, receiver, "mixer", None,
                                  decision_cfg) == sender
    assert engine._subject_wallet(sender, receiver, None, None,
                                  decision_cfg) == sender


def test_title_names_entity_and_cause():
    """Заголовок описывает сущность и находку, а не отдельную транзакцию."""
    title = engine._entity_title("0xd90e2f925da726b50c4ed8", "hard:sanctioned")
    assert title.startswith("Кошелёк 0xd90e2f92")
    assert "санкцион" in title.lower()

    summary = (300, datetime(2022, 3, 29, tzinfo=timezone.utc),
               datetime(2026, 7, 27, tzinfo=timezone.utc), Decimal(0))
    with_counts = engine._entity_title("0xd90e2f925da726b50c4ed8", "hard:sanctioned", summary)
    assert "300" in with_counts and "29.03.2022" in with_counts
