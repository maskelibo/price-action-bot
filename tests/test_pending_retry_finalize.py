"""F4 retry-koruma zinciri — kapanış sprinti 2026-07-10 (DERIN_DENETIM F4 CRIT).

Deferred-retry başarısı KORUMASIZ (SL/TP'siz) + JOURNAL'SIZ pozisyon
bırakıyordu — eski kod yorumu itiraf ediyordu ('journal yazma daemonun işi')
ama daemon timeout dalında fill'den habersizdi. Üstüne: exchange init hayalet
env (PA_BINANCE_*, boş) kullanıyordu ve 'side' long/short'u ccxt'ye ham
geçiyordu — retry yolu fiilen HİÇ uçtan uca çalışmamıştı.

Fix: get_futures_exchange + side haritası + çift-giriş kalkanı
(_check_existing_fill) + _finalize_fill (koruma→journal→idempotency).
"""

from __future__ import annotations

import copy
import json
import os
import subprocess
import sys
import textwrap
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock

import duckdb
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

import scripts.futures_daemon as daemon  # noqa: E402
import scripts.process_pending_entries as ppe  # noqa: E402


class FakeExchange:
    """create_order/fetch_order çağrılarını kaydeden minimal borsa."""

    def __init__(self, existing_orders=None):
        self.orders_created = []
        self.existing = existing_orders or {}  # coid -> order dict
        self.cancelled = []
        self._i = 0

    def amount_to_precision(self, symbol, x):
        return str(x)

    def price_to_precision(self, symbol, x):
        return str(x)

    def create_order(self, symbol, type, side, amount, params):
        self._i += 1
        self.orders_created.append(
            {"symbol": symbol, "type": type, "side": side, "amount": amount, "params": dict(params)}
        )
        return {"id": f"ord{self._i}"}

    def create_market_order(self, symbol, side, amount, params=None):
        self._i += 1
        self.orders_created.append(
            {
                "symbol": symbol,
                "type": "MARKET",
                "side": side,
                "amount": amount,
                "params": dict(params or {}),
            }
        )
        return {"id": f"mkt{self._i}", "filled": amount, "average": 100.0}

    def fetch_order(self, order_id, symbol, params=None):
        coid = (params or {}).get("origClientOrderId")
        if coid is not None:
            if coid in self.existing:
                return self.existing[coid]
            raise Exception("OrderNotFound")
        return {"id": order_id, "filled": 2.0, "average": 100.0}

    def cancel_order(self, order_id, symbol):
        self.cancelled.append(order_id)


def _entry(**over):
    e = {
        "ts": datetime.now(UTC).isoformat(),
        "symbol": "DOGE/USDT",
        "strategy": "vsa_climax_test",
        "side": "short",
        "qty": 2327.0,
        "entry_px": 0.155,
        "sl_price": 0.1638,
        "tp_price": 0.1497,
        "leverage": 1,
        "client_order_id": "PA_abc123",
        "attempts": 1,
        "max_attempts": 2,
    }
    e.update(over)
    return e


def _init_journal(path: Path) -> None:
    import os

    os.environ.setdefault("PA_BOT_NAME", "f4test")
    con = duckdb.connect(str(path))
    con.execute("""CREATE TABLE futures_signals (
        signal_id VARCHAR PRIMARY KEY, ts TIMESTAMP, symbol VARCHAR, strategy VARCHAR,
        side VARCHAR, sl_price DOUBLE, tp_price DOUBLE, confluence DOUBLE,
        leverage INTEGER, status VARCHAR, order_id VARCHAR, fill_price DOUBLE,
        fill_qty DOUBLE, notional_usdt DOUBLE, margin_usdt DOUBLE, notes VARCHAR)""")
    con.execute("""CREATE TABLE futures_protection_orders (
        prot_id VARCHAR PRIMARY KEY, ts TIMESTAMP, signal_id VARCHAR, symbol VARCHAR,
        side VARCHAR, qty DOUBLE, tp_price DOUBLE, sl_price DOUBLE,
        tp_order_id VARCHAR, sl_order_id VARCHAR, status VARCHAR, notes VARCHAR)""")
    con.commit()
    con.close()


def test_finalize_places_protection_with_queue_sl_tp(tmp_path):
    """ÇEKİRDEK: retry-fill sonrası SL (kuyruk sl_price'ında, reduceOnly) + TP kondu."""
    j = tmp_path / "j.duckdb"
    _init_journal(j)
    ex = FakeExchange()
    order = {"id": "mkt1", "filled": 2327.0, "average": 0.1551}
    res = ppe._finalize_fill(_entry(), order, ex, str(j), str(tmp_path / "idem.duckdb"))
    assert res["protection"] == "placed"
    sls = [o for o in ex.orders_created if o["type"] == "STOP_MARKET"]
    tps = [o for o in ex.orders_created if o["type"] == "TAKE_PROFIT_MARKET"]
    assert len(sls) == 1
    assert abs(float(sls[0]["params"]["stopPrice"]) - 0.1638) < 1e-9
    assert sls[0]["params"]["reduceOnly"] is True
    assert sls[0]["side"] == "BUY"  # short pozisyonun SL'i BUY
    assert len(tps) >= 1
    assert abs(sls[0]["amount"] - 2327.0) < 1e-6  # SL tam qty


def test_slippage_breach_is_durably_owned_journaled_and_plan_tamper_is_rejected(tmp_path):
    import scripts.futures_daemon as daemon
    import scripts.futures_trade_daily as futures_trade_daily

    ex = FakeExchange()
    signal = {
        "ts": datetime.now(UTC).isoformat(),
        "symbol": "DOGE/USDT",
        "strategy": "vsa",
        "side": "short",
        "sl_price": 110.0,
        "tp_price": 90.0,
        "confluence": 2.0,
    }
    plan = futures_trade_daily.build_protection_plan(
        ex,
        symbol="DOGE/USDT",
        side="short",
        qty=2.0,
        tp_price=90.0,
        sl_price=110.0,
        entry_price=100.0,
        protection_key="PA_breach_entry",
    )
    breach = {
        "schema_version": 1,
        "outcome_type": "slippage_breach",
        "disposition": "protect_position",
        "terminal": False,
        "position_owned": True,
        "protection_required": True,
        "unwind_attempted": False,
        "symbol": "DOGE/USDT",
        "entry_side": "sell",
        # Router cumQuote aggregate and later userTrades aggregate can differ
        # by harmless decimal summation dust while describing the same fill.
        "owned_quantity": 2.000000001,
        "owned_average": 100.0000005,
        "target_price": 99.7,
        "slippage_bps": 30.0,
        "limit_bps": 25.0,
        "fill_evidence_verified": True,
        "partial_limit_order_id": None,
        "market_fallback_order_id": "mkt-breach",
    }
    work = daemon._build_protection_finalize_entry(
        signal,
        exchange=ex,
        client_order_id="PA_breach_entry",
        order={"id": "mkt-breach", "slippage_breach": breach},
        fill_method="market_fallback_slippage_breach_protect",
        entry_execution_evidence={
            "schema_version": 1,
            "expected_price": 99.7,
            "realized_price": 100.0,
            "quantity": 2.0,
            "notional_usdt": 200.0,
            "fee_usdt": None,
            "fee_source": "unavailable",
            "is_maker": False,
            "order_type": "market",
            "maker_quantity": 0.0,
            "maker_notional_usdt": 0.0,
            "fill_method": "market_fallback_slippage_breach_protect",
            "exchange_order_id": "mkt-breach",
            "order_ids": ["mkt-breach"],
        },
        fill_qty=2.0,
        fill_price=100.0,
        fill_notional=200.0,
        fill_source="router_verified",
        leverage=1,
        signal_id="sig-breach",
        protection_id="prot-breach",
        protection_plan=plan,
    )
    work["slippage_db"] = str(tmp_path / "breach-fills.duckdb")

    assert ppe._validated_protection_finalize_work(work) is work
    assert work["entry_execution_outcome"]["position_owned"] is True
    assert work["entry_execution_outcome"]["unwind_attempted"] is False
    assert work["entry_execution_outcome"]["owned_average"] != work["entry_px"]

    journal = tmp_path / "breach.duckdb"
    _init_journal(journal)
    finalized = ppe._finalize_fill(
        work,
        ppe._protection_finalize_order(work),
        ex,
        str(journal),
        str(tmp_path / "breach-idem.duckdb"),
    )
    assert finalized["finalized"] is True
    con = duckdb.connect(str(journal), read_only=True)
    signal_notes = con.execute(
        "SELECT notes FROM futures_signals WHERE signal_id='sig-breach'"
    ).fetchone()[0]
    protection_notes = con.execute(
        "SELECT notes FROM futures_protection_orders WHERE prot_id='prot-breach'"
    ).fetchone()[0]
    con.close()
    assert "disposition=protect_position" in signal_notes
    assert "unwind_attempted=false" in protection_notes

    ownership_tampered = copy.deepcopy(work)
    ownership_tampered["entry_execution_outcome"]["owned_average"] = 100.01
    ownership_tampered["protection_binding_sha256"] = ppe._protection_finalize_binding_sha256(
        ownership_tampered
    )
    with pytest.raises(ValueError, match="ownership/fill mismatch"):
        ppe._validated_protection_finalize_work(ownership_tampered)

    tampered = copy.deepcopy(work)
    tampered["protection_plan"]["legs"][0]["amount"] = "1.0"
    tampered["protection_plan"]["plan_sha256"] = futures_trade_daily._protection_plan_hash(
        tampered["protection_plan"]
    )
    # Recomputing the plan's self-hash cannot update its independent WAL binding.
    tamper_exchange = FakeExchange()
    with pytest.raises(ValueError, match="semantic binding mismatch"):
        ppe._validated_protection_finalize_work(tampered)
    assert tamper_exchange.orders_created == []


def test_finalize_pins_protection_to_original_entry_client_id(tmp_path, monkeypatch):
    """A later identical trade must not reconcile this entry's old TP/SL legs."""
    import scripts.futures_trade_daily as futures_trade_daily

    journal = tmp_path / "j.duckdb"
    _init_journal(journal)
    captured: dict[str, object] = {}

    def fake_protection(*_args, **kwargs):
        captured.update(kwargs)
        return {
            "status": "placed",
            "mode": "multi_target",
            "tp_price": 0.1464,
            "tp2_price": 0.1421,
            "sl_price": 0.1638,
            "tp_order_id": "tp1",
            "tp2_order_id": "tp2",
            "sl_order_id": "sl1",
        }

    monkeypatch.setattr(futures_trade_daily, "place_protection_orders", fake_protection)
    result = ppe._finalize_fill(
        _entry(client_order_id="PA_unique-entry"),
        {"id": "mkt1", "filled": 2327.0, "average": 0.1551},
        FakeExchange(),
        str(journal),
        str(tmp_path / "idem.duckdb"),
    )

    assert result["finalized"] is True
    assert captured["protection_key"] == "PA_unique-entry"


def test_finalize_inserts_journal_rows(tmp_path):
    j = tmp_path / "j.duckdb"
    _init_journal(j)
    ex = FakeExchange()
    order = {"id": "mkt1", "filled": 2327.0, "average": 0.1551}
    res = ppe._finalize_fill(_entry(), order, ex, str(j), str(tmp_path / "idem.duckdb"))
    assert res["journal"] is True
    con = duckdb.connect(str(j), read_only=True)
    sig = con.execute(
        "SELECT symbol, side, status, notes, fill_qty FROM futures_signals"
    ).fetchone()
    prot = con.execute("SELECT signal_id, status, notes FROM futures_protection_orders").fetchone()
    con.close()
    assert sig == ("DOGE/USDT", "short", "filled", "resolved_by_retry", 2327.0)
    assert prot[0] == res["sig_id"]
    assert prot[1] == "placed"
    assert "resolved_by_retry" in prot[2]


def test_finalize_marks_idempotency(tmp_path):
    from price_action.execution.idempotency import IdempotencyStore

    j = tmp_path / "j.duckdb"
    _init_journal(j)
    idem_db = tmp_path / "idem.duckdb"
    IdempotencyStore(db_path=idem_db)  # şema kur (mark_filled upsert eder)
    ex = FakeExchange()
    order = {"id": "mkt1", "filled": 2327.0, "average": 0.1551}
    res = ppe._finalize_fill(_entry(), order, ex, str(j), str(idem_db))
    assert res["idempotency"] is True


def test_deferred_retry_execution_evidence_is_replay_exactly_once(tmp_path, monkeypatch):
    import scripts.futures_trade_daily as futures_trade_daily

    journal = tmp_path / "journal.duckdb"
    slippage_db = tmp_path / "fills.duckdb"
    idem_db = tmp_path / "idem.duckdb"
    _init_journal(journal)

    def stable_protection(*_args, **_kwargs):
        return {
            "status": "placed",
            "mode": "single_target",
            "tp_price": 0.1497,
            "sl_price": 0.1638,
            "tp_order_id": "tp-stable",
            "sl_order_id": "sl-stable",
        }

    monkeypatch.setattr(futures_trade_daily, "place_protection_orders", stable_protection)
    entry = _entry(
        ts="2026-07-11T09:00:00+00:00",
        slippage_db=str(slippage_db),
        tf="15m",
    )
    order = {"id": "entry-stable", "filled": 2327.0, "average": 0.1551}

    first = ppe._finalize_fill(entry, order, FakeExchange(), str(journal), str(idem_db))
    second = ppe._finalize_fill(entry, order, FakeExchange(), str(journal), str(idem_db))

    assert first["finalized"] is True
    assert second["finalized"] is True
    with duckdb.connect(str(slippage_db), read_only=True) as con:
        rows = con.execute(
            """SELECT fill_id, fee_usdt, fee_source, is_maker,
                      maker_quantity, maker_notional_usdt, order_type
                 FROM fills"""
        ).fetchall()
    assert rows == [
        (
            f"entry_{first['sig_id']}",
            None,
            "unavailable",
            False,
            0.0,
            0.0,
            "deferred_reconcile_unknown",
        )
    ]


def test_check_existing_fill_returns_prior_fill():
    """Attempt-1'in -1007-sonrası aslında DOLMUŞ emri bulunur → yeni emir YOK."""
    existing = {
        "PA_abc123-r1": {"id": "old1", "status": "closed", "filled": 2327.0, "average": 0.155}
    }
    ex = FakeExchange(existing_orders=existing)
    found = ppe._check_existing_fill(ex, _entry(attempts=1))
    assert found is not None and found["id"] == "old1"
    assert ex.orders_created == []  # yeni emir atılmadı


def test_check_existing_fill_none_when_no_orders():
    ex = FakeExchange()
    assert ppe._check_existing_fill(ex, _entry()) is None


def test_check_existing_open_cancel_without_terminal_verify_is_held():
    existing = {"PA_abc123": {"id": "open1", "status": "open", "filled": 0}}
    ex = FakeExchange(existing_orders=existing)
    with pytest.raises(ppe.ExistingOrderStateUncertainError, match="cancel_verify"):
        ppe._check_existing_fill(ex, _entry(attempts=0))
    assert "open1" in ex.cancelled
    assert ex.orders_created == []


def test_transient_existing_lookup_never_allows_retry_submit():
    """Network lookup failure is not OrderNotFound and cannot open a new order."""

    class TransientLookupExchange(FakeExchange):
        def fetch_order(self, order_id, symbol, params=None):
            raise TimeoutError("temporary lookup timeout")

    ex = TransientLookupExchange()
    with pytest.raises(ppe.ExistingOrderStateUncertainError, match="stage=lookup"):
        ppe._check_existing_fill(ex, _entry(attempts=1))
    assert ex.orders_created == []


def test_try_retry_transient_lookup_returns_fail_closed_without_submit(monkeypatch):
    """The public queue step also stops before ticker/order creation."""

    class TransientLookupExchange(FakeExchange):
        def fetch_order(self, order_id, symbol, params=None):
            raise TimeoutError("temporary lookup timeout")

        def fetch_ticker(self, symbol):
            raise AssertionError("ticker must not be reached")

    ex = TransientLookupExchange()
    import scripts.futures_trade_daily as futures_trade_daily

    monkeypatch.setattr(futures_trade_daily, "get_futures_exchange", lambda: ex)
    success, order, reason, returned_ex = ppe._try_retry(_entry(attempts=1))
    assert success is False
    assert order is None
    assert reason.startswith("reconcile_uncertain")
    assert returned_ex is ex
    assert ex.orders_created == []


def test_successful_retry_ack_persists_identity_before_finalize(monkeypatch):
    """Protection/finalize failure cannot forget the retry order it already submitted."""

    class SubmitExchange(FakeExchange):
        def fetch_ticker(self, symbol):
            return {"last": 0.155}

    exchange = SubmitExchange()
    import scripts.futures_trade_daily as futures_trade_daily

    monkeypatch.setattr(futures_trade_daily, "get_futures_exchange", lambda: exchange)
    entry = _entry(attempts=0)
    success, order, reason, _returned_exchange = ppe._try_retry(entry)

    assert success is True
    assert order is not None and order["id"] == "mkt1"
    assert reason == "retry_attempt_1"
    assert entry["attempts"] == 1
    assert entry["reconcile_only"] is True
    assert entry["known_order_ids"] == ["mkt1"]
    assert entry["last_submitted_client_order_id"] == "PA_abc123-r1"


def test_ack_identity_survives_crash_before_finalize_and_prevents_resubmit(tmp_path, monkeypatch):
    """ACK transition is on disk before protection/journal code can crash."""

    class DurableAckExchange(FakeExchange):
        def __init__(self):
            super().__init__()
            self.ack_order = None

        def fetch_ticker(self, symbol):
            return {"last": 0.155}

        def create_market_order(self, symbol, side, amount, params=None):
            order = super().create_market_order(symbol, side, amount, params=params)
            order.update({"status": "closed", "filled": amount, "average": 0.155})
            self.ack_order = dict(order)
            self.ack_order["clientOrderId"] = (params or {}).get("newClientOrderId")
            return order

        def fetch_order(self, order_id, symbol, params=None):
            coid = (params or {}).get("origClientOrderId")
            if self.ack_order is not None and (
                order_id == self.ack_order["id"] or coid == self.ack_order["clientOrderId"]
            ):
                return dict(self.ack_order)
            raise Exception("OrderNotFound")

    import scripts.futures_trade_daily as futures_trade_daily

    exchange = DurableAckExchange()
    monkeypatch.setattr(futures_trade_daily, "get_futures_exchange", lambda: exchange)
    queue_path = tmp_path / "pending.jsonl"
    entry = _entry(
        attempts=0,
        terminal_no_fill_confirmations=2,
        terminal_no_fill_confirmations_required=2,
    )
    queue_path.write_text(json.dumps(entry) + "\n", encoding="utf-8")
    monkeypatch.setattr(ppe, "_QUEUE_PATH", queue_path)
    monkeypatch.setattr(
        ppe,
        "_finalize_fill",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(KeyboardInterrupt("crash")),
    )

    with pytest.raises(KeyboardInterrupt, match="crash"):
        ppe.process_pending()

    durable = json.loads(queue_path.read_text(encoding="utf-8"))
    assert durable["attempts"] == 1
    assert durable["reconcile_only"] is True
    assert durable["known_order_ids"] == ["mkt1"]
    assert durable["last_submitted_client_order_id"] == "PA_abc123-r1"
    assert len(exchange.orders_created) == 1

    monkeypatch.setattr(
        ppe,
        "_finalize_fill",
        lambda *_args, **_kwargs: {
            "verified": True,
            "finalized": True,
            "retryable": False,
            "protection": "placed",
            "journal": True,
            "idempotency": True,
            "fill_qty": 2327.0,
            "avg_px": 0.155,
        },
    )
    second = ppe.process_pending()

    assert second["success"] == 1
    assert len(exchange.orders_created) == 1
    assert not queue_path.exists()


def test_retry_identity_is_write_ahead_durable_if_process_dies_during_submit(tmp_path, monkeypatch):
    """A crash inside the HTTP submit cannot erase the possibly accepted -rN id."""

    class SubmitCrashExchange(FakeExchange):
        def fetch_ticker(self, symbol):
            return {"last": 0.155}

        def create_market_order(self, symbol, side, amount, params=None):
            self.orders_created.append(
                {
                    "symbol": symbol,
                    "side": side,
                    "amount": amount,
                    "params": dict(params or {}),
                }
            )
            raise KeyboardInterrupt("host died during submit")

    import scripts.futures_trade_daily as futures_trade_daily

    exchange = SubmitCrashExchange()
    monkeypatch.setattr(futures_trade_daily, "get_futures_exchange", lambda: exchange)
    queue_path = tmp_path / "pending.jsonl"
    queue_path.write_text(
        json.dumps(
            _entry(
                attempts=0,
                terminal_no_fill_confirmations=1,
                terminal_no_fill_confirmations_required=2,
            )
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(ppe, "_QUEUE_PATH", queue_path)

    with pytest.raises(KeyboardInterrupt, match="host died"):
        ppe.process_pending()

    durable = json.loads(queue_path.read_text(encoding="utf-8"))
    assert durable["attempts"] == 1
    assert durable["terminal_no_fill_confirmations"] == 0
    assert durable["last_submitted_client_order_id"] == "PA_abc123-r1"
    assert durable["uncertain_client_order_ids"] == ["PA_abc123-r1"]
    assert durable["submit_uncertainty"]["stage"] == "retry_market_submit_prepared"
    assert "PA_abc123-r1" in ppe._coid_candidates(durable)
    assert len(exchange.orders_created) == 1


@pytest.mark.subprocess
def test_real_process_exit_then_two_processor_barrier_is_exactly_once(tmp_path):
    """ACK survives ``os._exit``; racing recovery yields one complete side effect set."""
    queue_path = tmp_path / "pending.jsonl"
    journal_path = tmp_path / "journal.duckdb"
    idempotency_path = tmp_path / "idempotency.duckdb"
    exchange_state = tmp_path / "fake_exchange.json"
    exchange_lock = tmp_path / "fake_exchange.lock"
    barrier = tmp_path / "go"
    ready_dir = tmp_path / "ready"
    ready_dir.mkdir()
    _init_journal(journal_path)
    exchange_state.write_text(
        json.dumps(
            {
                "market_orders": {},
                "protection_orders": {},
                "submit_count": 0,
                "protection_submit_count": 0,
            }
        ),
        encoding="utf-8",
    )
    ppe.append_pending_entry(
        queue_path,
        _entry(
            # Keep the subprocess entry inside its age budget regardless of
            # the wall-clock hour in which the suite is executed.
            ts=(datetime.now(UTC) - timedelta(seconds=1)).isoformat(),
            symbol="BTC/USDT:USDT",
            side="long",
            qty=2.0,
            entry_px=100.0,
            sl_price=95.0,
            tp_price=110.0,
            client_order_id="PA_crash_exactly_once",
            attempts=0,
            max_age_seconds=3600,
            terminal_no_fill_confirmations=1,
            terminal_no_fill_confirmations_required=2,
            journal_db=str(journal_path),
            idempotency_db=str(idempotency_path),
        ),
    )

    helper_path = tmp_path / "crash_exchange.py"
    helper_path.write_text(
        textwrap.dedent(
            """
            from __future__ import annotations

            import fcntl
            import json
            import os
            import tempfile
            from contextlib import contextmanager
            from pathlib import Path

            import ccxt

            STATE = Path(os.environ["PA_TEST_EXCHANGE_STATE"])
            LOCK = Path(os.environ["PA_TEST_EXCHANGE_LOCK"])


            def _fsync_parent(path: Path) -> None:
                fd = os.open(path.parent, os.O_RDONLY)
                try:
                    os.fsync(fd)
                finally:
                    os.close(fd)


            @contextmanager
            def _state(*, write: bool = False):
                with open(LOCK, "a+", encoding="utf-8") as lock:
                    fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
                    data = json.loads(STATE.read_text(encoding="utf-8"))
                    yield data
                    if write:
                        fd, raw = tempfile.mkstemp(dir=STATE.parent, prefix=".fake-exchange-")
                        try:
                            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                                handle.write(json.dumps(data, sort_keys=True))
                                handle.flush()
                                os.fsync(handle.fileno())
                            os.replace(raw, STATE)
                            _fsync_parent(STATE)
                        finally:
                            if os.path.exists(raw):
                                os.unlink(raw)
                    fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


            class FakeExchange:
                def amount_to_precision(self, _symbol, value):
                    return f"{float(value):.8f}".rstrip("0").rstrip(".")

                def price_to_precision(self, _symbol, value):
                    return f"{float(value):.8f}".rstrip("0").rstrip(".")

                def fetch_ticker(self, _symbol):
                    return {"last": 100.0}

                def fetch_order(self, order_id, _symbol, params=None):
                    params = dict(params or {})
                    with _state() as data:
                        if params.get("conditional"):
                            client_id = params.get("clientAlgoId") or params.get("origClientOrderId")
                            order = data["protection_orders"].get(str(client_id or ""))
                        elif params.get("origClientOrderId"):
                            order = data["market_orders"].get(str(params["origClientOrderId"]))
                        else:
                            order = next(
                                (
                                    value
                                    for value in data["market_orders"].values()
                                    if str(value.get("id")) == str(order_id)
                                ),
                                None,
                            )
                    if order is None:
                        raise ccxt.OrderNotFound("OrderNotFound")
                    return dict(order)

                def create_market_order(self, symbol, side, amount, params=None):
                    client_id = str((params or {})["newClientOrderId"])
                    with _state(write=True) as data:
                        existing = data["market_orders"].get(client_id)
                        if existing is not None:
                            return dict(existing)
                        data["submit_count"] += 1
                        order = {
                            "id": f"market-{data['submit_count']}",
                            "clientOrderId": client_id,
                            "symbol": symbol,
                            "side": side,
                            "status": "closed",
                            "filled": float(amount),
                            "average": 100.0,
                            "cost": float(amount) * 100.0,
                        }
                        data["market_orders"][client_id] = order
                        return dict(order)

                def create_order(self, symbol, type, side, amount, params):
                    client_id = str(params["newClientOrderId"])
                    with _state(write=True) as data:
                        existing = data["protection_orders"].get(client_id)
                        if existing is not None:
                            return dict(existing)
                        data["protection_submit_count"] += 1
                        order = {
                            "id": f"algo-{data['protection_submit_count']}",
                            "clientOrderId": client_id,
                            "symbol": symbol,
                            "type": type,
                            "side": side,
                            "amount": float(amount),
                            "triggerPrice": params["stopPrice"],
                            "reduceOnly": True,
                            "status": "open",
                        }
                        data["protection_orders"][client_id] = order
                        return dict(order)
            """
        ),
        encoding="utf-8",
    )

    env = os.environ.copy()
    env.update(
        {
            "PYTHONPATH": os.pathsep.join((str(tmp_path), str(ROOT), str(ROOT / "src"))),
            "PA_TEST_EXCHANGE_STATE": str(exchange_state),
            "PA_TEST_EXCHANGE_LOCK": str(exchange_lock),
        }
    )
    crash_code = textwrap.dedent(
        """
        import os
        import sys
        from pathlib import Path

        import crash_exchange
        import scripts.futures_trade_daily as ftd
        import scripts.process_pending_entries as ppe

        ppe._QUEUE_PATH = Path(sys.argv[1])
        ftd.get_futures_exchange = crash_exchange.FakeExchange

        def die_after_durable_ack(*_args, **_kwargs):
            os._exit(77)

        ppe._finalize_fill = die_after_durable_ack
        ppe.process_pending()
        """
    )
    crashed = subprocess.run(
        [sys.executable, "-c", crash_code, str(queue_path)],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert crashed.returncode == 77, (crashed.stdout, crashed.stderr)
    durable = json.loads(queue_path.read_text(encoding="utf-8"))
    assert durable["reconcile_only"] is True
    assert durable["known_order_ids"] == ["market-1"]
    assert durable["last_submitted_client_order_id"].endswith("-r1")

    worker_code = textwrap.dedent(
        """
        import json
        import os
        import sys
        import time
        from pathlib import Path

        import crash_exchange
        import scripts.futures_trade_daily as ftd
        import scripts.process_pending_entries as ppe

        ppe._QUEUE_PATH = Path(sys.argv[1])
        barrier = Path(sys.argv[2])
        ready_dir = Path(sys.argv[3])
        ftd.get_futures_exchange = crash_exchange.FakeExchange
        original_protection = ftd.place_protection_orders

        def slow_protection(*args, **kwargs):
            time.sleep(0.4)
            return original_protection(*args, **kwargs)

        ftd.place_protection_orders = slow_protection
        (ready_dir / str(os.getpid())).write_text("ready", encoding="ascii")
        deadline = time.monotonic() + 10
        while not barrier.exists():
            if time.monotonic() > deadline:
                raise TimeoutError("barrier was never released")
            time.sleep(0.01)
        print("RESULT=" + json.dumps(ppe.process_pending(), sort_keys=True), flush=True)
        """
    )
    workers = [
        subprocess.Popen(
            [sys.executable, "-c", worker_code, str(queue_path), str(barrier), str(ready_dir)],
            cwd=ROOT,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        for _ in range(2)
    ]
    deadline = time.monotonic() + 15
    while len(list(ready_dir.iterdir())) < 2 and time.monotonic() < deadline:
        time.sleep(0.02)
    assert len(list(ready_dir.iterdir())) == 2
    barrier.write_text("go", encoding="ascii")
    outputs = [worker.communicate(timeout=20) for worker in workers]
    assert all(worker.returncode == 0 for worker in workers), outputs
    results = []
    for stdout, stderr in outputs:
        line = next((item for item in stdout.splitlines() if item.startswith("RESULT=")), None)
        assert line is not None, (stdout, stderr)
        results.append(json.loads(line.removeprefix("RESULT=")))
    assert sorted(result["success"] for result in results) == [0, 1]
    assert sorted(result["busy"] for result in results) == [0, 1]

    state = json.loads(exchange_state.read_text(encoding="utf-8"))
    assert state["submit_count"] == 1
    assert state["protection_submit_count"] == 3
    assert len(state["protection_orders"]) == 3
    assert not queue_path.exists()
    with duckdb.connect(str(journal_path), read_only=True) as connection:
        assert connection.execute("SELECT count(*) FROM futures_signals").fetchone()[0] == 1
        assert (
            connection.execute("SELECT count(*) FROM futures_protection_orders").fetchone()[0] == 1
        )


@pytest.mark.subprocess
def test_processor_lease_is_cross_process_and_does_not_block_daemon_append(tmp_path):
    queue_path = tmp_path / "pending.jsonl"
    first = _entry(client_order_id="PA_first")
    second = _entry(symbol="XRP/USDT", client_order_id="PA_second")
    ppe.append_pending_entry(queue_path, first)
    code = """
import json
import sys
from pathlib import Path
import scripts.process_pending_entries as ppe
ppe._QUEUE_PATH = Path(sys.argv[1])
print("RESULT=" + json.dumps(ppe.process_pending(), sort_keys=True))
"""
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT / "src")

    with ppe._processor_lease(queue_path) as acquired:
        assert acquired is True
        # Separate queue lock: daemon append is not blocked by processor lease.
        ppe.append_pending_entry(queue_path, second)
        completed = subprocess.run(
            [sys.executable, "-c", code, str(queue_path)],
            cwd=ROOT,
            env=env,
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )

    assert completed.returncode == 0, completed.stderr
    result_line = next(line for line in completed.stdout.splitlines() if line.startswith("RESULT="))
    result = json.loads(result_line.removeprefix("RESULT="))
    assert result["busy"] == 1
    assert result["read"] == 0
    persisted = [json.loads(line) for line in queue_path.read_text().splitlines()]
    assert {item["client_order_id"] for item in persisted} == {"PA_first", "PA_second"}


def test_main_partial_and_market_fallback_are_discovered_and_aggregated():
    """Queue queries both base and `_fb`; protection input is total exchange fill."""
    existing = {
        "PA_abc123": {
            "id": "limit1",
            "status": "canceled",
            "filled": 0.4,
            "average": 100.0,
            "cost": 40.0,
        },
        "PA_abc123_fb": {
            "id": "market1",
            "status": "closed",
            "filled": 0.6,
            "average": 101.0,
            "cost": 60.6,
        },
    }
    ex = FakeExchange(existing_orders=existing)
    found = ppe._check_existing_fill(ex, _entry(attempts=0))
    assert found is not None
    assert found["id"] == "limit1,market1"
    assert found["filled"] == pytest.approx(1.0)
    assert found["average"] == pytest.approx(100.6)
    assert found["cost"] == pytest.approx(100.6)
    assert found["fill_price_verified"] is True


def test_unverified_fill_never_uses_intended_qty_or_entry_price(tmp_path, monkeypatch):
    """No exchange fill facts means no fake journal and no wrong protection."""

    class NoEvidenceExchange(FakeExchange):
        def fetch_order(self, order_id, symbol, params=None):
            raise TimeoutError("fill details unavailable")

        def fetch_my_trades(self, symbol):
            return []

    journal = tmp_path / "j.duckdb"
    _init_journal(journal)
    audits: list[str] = []
    monkeypatch.setattr(
        ppe,
        "_audit_unverified_fill",
        lambda _entry_arg, _order_arg, reason: audits.append(reason),
    )
    ex = NoEvidenceExchange()
    order = {"id": "unknown-fill", "status": "closed", "filled": None, "average": None}

    result = ppe._finalize_fill(
        _entry(qty=999.0, entry_px=123.45),
        order,
        ex,
        str(journal),
        str(tmp_path / "idem.duckdb"),
    )

    assert result["verified"] is False
    assert result["fill_qty"] is None
    assert result["avg_px"] is None
    assert result["protection"] is None
    assert result["journal"] is False
    assert ex.orders_created == []
    assert audits and "exchange qty+average unavailable" in audits[0]
    con = duckdb.connect(str(journal), read_only=True)
    try:
        assert con.execute("SELECT count(*) FROM futures_signals").fetchone()[0] == 0
        assert con.execute("SELECT count(*) FROM futures_protection_orders").fetchone()[0] == 0
    finally:
        con.close()


def test_protection_failure_is_retryable_and_not_journaled(tmp_path, monkeypatch):
    """Verified fill is not terminal success until SL/TP placement succeeds."""
    import scripts.futures_trade_daily as futures_trade_daily

    journal = tmp_path / "j.duckdb"
    _init_journal(journal)
    monkeypatch.setattr(
        futures_trade_daily,
        "place_protection_orders",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("algo API unavailable")),
    )

    result = ppe._finalize_fill(
        _entry(),
        {"id": "mkt1", "status": "closed", "filled": 2.0, "average": 0.1551},
        FakeExchange(),
        str(journal),
        str(tmp_path / "idem.duckdb"),
    )

    assert result["verified"] is True
    assert result["protection"] == "error"
    assert result["finalized"] is False
    assert result["retryable"] is True
    assert result["journal"] is False
    assert result["idempotency"] is False
    assert result["failure_reason"].startswith("protection_not_placed")
    with duckdb.connect(str(journal), read_only=True) as connection:
        assert connection.execute("SELECT count(*) FROM futures_signals").fetchone()[0] == 0
        assert (
            connection.execute("SELECT count(*) FROM futures_protection_orders").fetchone()[0] == 0
        )


def test_fill_price_can_be_verified_from_user_trades():
    """Delayed order average is resolved from matching exchange trade facts."""

    class TradeEvidenceExchange:
        def fetch_order(self, order_id, symbol):
            raise TimeoutError("normalized order details delayed")

        def fetch_my_trades(self, symbol):
            return [
                {"id": "t1", "order": "mkt1", "amount": 1.0, "cost": 100.0},
                {"id": "t2", "order": "mkt1", "amount": 1.0, "cost": 102.0},
            ]

    evidence = ppe._resolve_verified_fill(
        _entry(),
        {"id": "mkt1", "status": "closed", "filled": 2.0, "average": None},
        TradeEvidenceExchange(),
    )
    assert evidence == pytest.approx({"qty": 2.0, "notional": 202.0, "average": 101.0})


def test_fill_can_use_position_risk_only_with_pre_submit_baseline():
    """Raw positionRisk is accepted only as a measured delta from queue metadata."""

    class PositionEvidenceExchange:
        def fetch_order(self, order_id, symbol):
            raise TimeoutError("order details delayed")

        def fapiPrivateGetUserTrades(self, params):  # noqa: N802 - CCXT raw API name
            return []

        def fapiPrivateGetPositionRisk(self, params):  # noqa: N802 - CCXT raw API name
            return [{"symbol": "DOGEUSDT", "positionAmt": "-2", "entryPrice": "0.1552"}]

    evidence = ppe._resolve_verified_fill(
        _entry(pre_submit_position_qty=0.0),
        {"id": "mkt2", "status": "closed", "filled": 2.0, "average": None},
        PositionEvidenceExchange(),
    )
    assert evidence == pytest.approx({"qty": 2.0, "notional": 0.3104, "average": 0.1552})


def test_max_attempt_entry_is_held_when_reconciliation_is_uncertain(tmp_path, monkeypatch):
    """Attempt exhaustion never discards a possibly-filled timed-out submit."""
    queue_path = tmp_path / "pending.jsonl"
    missed_path = tmp_path / "missed.jsonl"
    entry = _entry(attempts=2, max_attempts=2, max_age_seconds=3600)
    queue_path.write_text(json.dumps(entry) + "\n", encoding="utf-8")
    monkeypatch.setattr(ppe, "_QUEUE_PATH", queue_path)
    monkeypatch.setattr(ppe, "_MISSED_PATH", missed_path)
    allow_submit_values: list[bool] = []

    def fake_try_retry(entry_arg, *, allow_submit=True, on_ack=None):
        allow_submit_values.append(allow_submit)
        return False, None, "reconcile_uncertain: exchange lookup timeout", object()

    monkeypatch.setattr(ppe, "_try_retry", fake_try_retry)
    stats = ppe.process_pending()

    assert allow_submit_values == [False]
    assert stats["retry_again"] == 1
    assert stats["dropped_attempts"] == 0
    held = json.loads(queue_path.read_text(encoding="utf-8"))
    assert held["attempts"] == 2
    assert not missed_path.exists()


def test_processor_holds_verified_fill_when_protection_is_not_placed(tmp_path, monkeypatch):
    queue_path = tmp_path / "pending.jsonl"
    entry = _entry(attempts=1, max_attempts=1)
    queue_path.write_text(json.dumps(entry) + "\n", encoding="utf-8")
    monkeypatch.setattr(ppe, "_QUEUE_PATH", queue_path)

    def fake_filled_retry(entry_arg, *, allow_submit=True, on_ack=None):
        order = {"id": "filled1", "resolved_order_ids": ["filled1"]}
        ppe._remember_acknowledged_order(entry_arg, order)
        if on_ack is not None:
            on_ack(entry_arg, order)
        return True, order, "resolved_from_existing_fill", object()

    monkeypatch.setattr(ppe, "_try_retry", fake_filled_retry)
    monkeypatch.setattr(
        ppe,
        "_finalize_fill",
        lambda *_args, **_kwargs: {
            "verified": True,
            "finalized": False,
            "retryable": True,
            "protection": "error",
            "failure_reason": "protection_not_placed: exchange unavailable",
            "fill_qty": 2.0,
            "avg_px": 100.0,
        },
    )

    stats = ppe.process_pending()

    assert stats["success"] == 0
    assert stats["retry_again"] == 1
    held = json.loads(queue_path.read_text(encoding="utf-8"))
    assert held["finalize_attempts"] == 1
    assert held["last_retry_reason"].startswith("protection_not_placed")
    assert held["reconcile_only"] is True
    assert held["known_order_ids"] == ["filled1"]


def test_daemon_append_during_processing_survives_atomic_merge(tmp_path, monkeypatch):
    """Regression: processor snapshot + daemon append + replace must not lose append."""
    queue_path = tmp_path / "pending.jsonl"
    old_entry = _entry(client_order_id="PA_old", attempts=1, max_attempts=1)
    new_entry = _entry(symbol="XRP/USDT", client_order_id="PA_new", attempts=0)
    queue_path.write_text(json.dumps(old_entry) + "\n", encoding="utf-8")
    monkeypatch.setattr(ppe, "_QUEUE_PATH", queue_path)
    monkeypatch.setattr(ppe, "_push_missed", lambda *_args, **_kwargs: None)

    def fake_try_retry(_entry_arg, *, allow_submit=True, on_ack=None):
        assert allow_submit is False
        ppe.append_pending_entry(queue_path, new_entry)
        return False, None, "submit_disabled_after_terminal_reconcile", object()

    monkeypatch.setattr(ppe, "_try_retry", fake_try_retry)
    stats = ppe.process_pending()

    assert stats["read"] == 1
    assert stats["retry_again"] == 1
    remaining = [json.loads(line) for line in queue_path.read_text(encoding="utf-8").splitlines()]
    assert {item["client_order_id"] for item in remaining} == {"PA_old", "PA_new"}


def test_all_uncertain_submits_require_two_terminal_confirmations_before_retry(
    tmp_path, monkeypatch
):
    queue_path = tmp_path / "pending.jsonl"
    queue_path.write_text(
        json.dumps(_entry(attempts=0, max_age_seconds=3600)) + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(ppe, "_QUEUE_PATH", queue_path)
    allow_submit_calls: list[bool] = []

    def fake_try_retry(_entry_arg, *, allow_submit=True, on_ack=None):
        allow_submit_calls.append(allow_submit)
        if not allow_submit:
            return False, None, "submit_disabled_after_terminal_reconcile", object()
        return False, None, "order_submit_uncertain: timeout after send", object()

    monkeypatch.setattr(ppe, "_try_retry", fake_try_retry)

    first = ppe.process_pending()
    second = ppe.process_pending()

    assert first["retry_again"] == 1
    assert second["retry_again"] == 1
    # The second call is allowed to submit because `_try_retry` performs the
    # second terminal reconciliation immediately before sending the retry.
    assert allow_submit_calls == [False, True]
    persisted = json.loads(queue_path.read_text(encoding="utf-8"))
    assert persisted["attempts"] == 1
    assert persisted["terminal_no_fill_confirmations"] == 0


def test_malformed_queue_fails_closed_without_side_effect_or_rewrite(tmp_path, monkeypatch):
    queue_path = tmp_path / "pending.jsonl"
    original = json.dumps(_entry()) + "\n" + "{malformed-json\n"
    queue_path.write_text(original, encoding="utf-8")
    monkeypatch.setattr(ppe, "_QUEUE_PATH", queue_path)
    monkeypatch.setattr(
        ppe,
        "_try_retry",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("exchange side effect must not run")
        ),
    )

    stats = ppe.process_pending()

    assert stats["malformed"] == 1
    assert stats["read"] == 0
    assert queue_path.read_text(encoding="utf-8") == original


def test_reconcile_only_ack_has_durable_order_identity_and_never_resubmits(tmp_path, monkeypatch):
    import scripts.futures_daemon as daemon
    import scripts.futures_trade_daily as futures_trade_daily

    entry = daemon._build_pending_retry_entry(
        {
            "symbol": "DOGE/USDT",
            "strategy": "vsa",
            "side": "short",
            "sl_price": 1.1,
            "tp_price": 0.9,
        },
        qty=2.0,
        entry_px=1.0,
        leverage=1,
        client_order_id="PA_ack",
        orig_error="fill evidence delayed",
        pre_submit_position_qty=0.0,
        pre_submit_position_entry_price=None,
        order={"id": "ack-order-1"},
        reconcile_only=True,
    )
    assert entry["reconcile_only"] is True
    assert entry["known_order_ids"] == ["ack-order-1"]
    assert entry["submitted_order_id"] == "ack-order-1"
    assert entry["protection_owner"] == "pending_retry_processor"
    assert entry["protection_intent_id"] == "PA_ack"
    assert entry["watchdog_protection_lease_seconds"] == 120.0
    assert entry["max_age_seconds"] == 180
    queue_path = tmp_path / "pending.jsonl"
    daemon._enqueue_pending_retry(entry, queue_path)
    persisted = json.loads(queue_path.read_text(encoding="utf-8"))
    assert persisted["known_order_ids"] == ["ack-order-1"]
    assert persisted["reconcile_only"] is True

    class AckExchange(FakeExchange):
        def fetch_order(self, order_id, symbol, params=None):
            if order_id == "ack-order-1":
                return {
                    "id": "ack-order-1",
                    "status": "closed",
                    "filled": 2.0,
                    "average": 1.0,
                }
            return super().fetch_order(order_id, symbol, params=params)

    exchange = AckExchange()
    monkeypatch.setattr(futures_trade_daily, "get_futures_exchange", lambda: exchange)
    success, order, reason, _returned_exchange = ppe._try_retry(entry, allow_submit=False)

    assert success is True
    assert reason == "resolved_from_existing_fill"
    assert order is not None and order["id"] == "ack-order-1"
    assert exchange.orders_created == []


def test_watchdog_holds_fresh_pending_owner_and_uses_original_levels():
    import scripts.futures_daemon as daemon

    now = datetime(2026, 7, 11, 12, 0, tzinfo=UTC)
    entry = _entry(
        ts=(now - timedelta(seconds=60)).isoformat(),
        tf="15m",
        side="short",
        sl_price=0.1638,
        tp_price=0.1497,
        max_age_seconds=120,
    )

    intent = daemon._pending_retry_watchdog_intent(entry, "DOGE/USDT:USDT", "short", now=now)

    assert intent is not None
    assert intent["lease_active"] is True
    assert intent["sl_price"] == pytest.approx(0.1638)
    assert intent["tp_price"] == pytest.approx(0.1497)
    assert daemon._pending_retry_watchdog_action(intent) == "hold_processor_owned"


def test_watchdog_pending_ownership_is_bounded_then_original_sl_takes_over():
    import scripts.futures_daemon as daemon

    now = datetime(2026, 7, 11, 12, 0, tzinfo=UTC)
    entry = _entry(
        ts=(now - timedelta(seconds=301)).isoformat(),
        tf="15m",
        max_age_seconds=999_999,  # corrupt/stale metadata cannot suppress forever
    )

    intent = daemon._pending_retry_watchdog_intent(entry, "DOGEUSDT", "sell", now=now)

    assert intent is not None
    assert intent["lease_seconds"] == 300.0
    assert intent["lease_active"] is False
    assert intent["sl_price"] == pytest.approx(entry["sl_price"])
    assert daemon._pending_retry_watchdog_action(intent) == "watchdog_takeover_original_levels"


def test_watchdog_pending_owner_requires_symbol_side_and_complete_sl_tp():
    import scripts.futures_daemon as daemon

    now = datetime.now(UTC)
    entry = _entry(ts=now.isoformat())

    assert daemon._pending_retry_watchdog_intent(entry, "XRP/USDT", "short", now=now) is None
    assert daemon._pending_retry_watchdog_intent(entry, "DOGE/USDT", "long", now=now) is None
    assert (
        daemon._pending_retry_watchdog_intent(
            {**entry, "tp_price": None}, "DOGE/USDT", "short", now=now
        )
        is None
    )
    current_bot = daemon._normalize_pending_bot(daemon._BOT_NAME)
    other_bot = "other_bot" if current_bot != "other_bot" else "third_bot"
    assert (
        daemon._pending_retry_watchdog_intent(
            {**entry, "bot_name": other_bot},
            "DOGE/USDT",
            "short",
            now=now,
        )
        is None
    )


def test_watchdog_does_not_claim_older_position_without_pending_fill_delta():
    import scripts.futures_daemon as daemon

    now = datetime.now(UTC)
    entry = _entry(
        ts=now.isoformat(),
        side="long",
        sl_price=0.1497,
        tp_price=0.1638,
        pre_submit_position_qty=5.0,
    )

    assert (
        daemon._pending_retry_watchdog_intent(
            entry,
            "DOGE/USDT",
            "long",
            position_contracts=5.0,
            now=now,
        )
        is None
    )
    claimed = daemon._pending_retry_watchdog_intent(
        entry,
        "DOGE/USDT",
        "long",
        position_contracts=7.0,
        now=now,
    )
    assert claimed is not None
    assert claimed["owner_id"] == entry["client_order_id"]


def test_watchdog_queue_read_uncertainty_is_fail_closed():
    import scripts.futures_daemon as daemon

    assert (
        daemon._pending_retry_watchdog_action(None, queue_read_fail_closed=True)
        == "hold_queue_uncertain"
    )


def test_pending_owner_hold_is_wired_before_any_watchdog_order_mutation():
    daemon_src = (ROOT / "scripts" / "futures_daemon.py").read_text(encoding="utf-8")
    owner_branch = daemon_src.index('if _pending_watchdog_action == "hold_processor_owned":')
    sl_scan = daemon_src.index("_expected_sl_side =", owner_branch)
    branch_src = daemon_src[owner_branch:sl_scan]

    assert "continue" in branch_src
    assert "create_order(" not in branch_src
    assert "fapiPrivateDeleteAlgoOrder" not in branch_src


def test_position_check_pending_owner_sends_no_fallback_or_close(monkeypatch):
    import scripts.futures_daemon as daemon
    import scripts.futures_trade_daily as futures_trade_daily

    now = datetime.now(UTC)
    pending = _entry(
        ts=now.isoformat(),
        tf="15m",
        qty=2.0,
        entry_px=1.0,
        sl_price=1.10,
        tp_price=0.90,
        pre_submit_position_qty=0.0,
    )
    exchange = MagicMock()
    exchange.fapiPrivateV2GetPositionRisk.return_value = []
    state = {
        "positions": [
            {
                "symbol": "DOGE/USDT:USDT",
                "side": "short",
                "contracts": 2.0,
                "entryPrice": 1.0,
                "markPrice": 1.01,
                "unrealizedPnl": -0.02,
            }
        ],
        "algo_orders": [],
        "algo_orders_ok": True,
        "regular_orders_ok": True,
        "positions_ok": True,
        "order_scope_ok": True,
        "exchange_state_complete": True,
        "journal_open_position_symbols": [],
        "n_algo_orders": 0,
        "n_open_orders": 0,
        "wallet_balance": 0.0,
        "margin_balance": 0.0,
        "available_balance": 0.0,
        "unrealized_pnl": -0.02,
    }
    logs: list[str] = []

    monkeypatch.setattr(futures_trade_daily, "get_futures_exchange", lambda: exchange)
    monkeypatch.setattr(futures_trade_daily, "fetch_futures_state", lambda _ex: state)
    monkeypatch.setattr(daemon, "_read_pending_retry_entries", lambda: ([pending], None))
    monkeypatch.setattr(daemon, "_pyramid_positions", {})
    monkeypatch.setattr(daemon, "log", logs.append)

    def _no_journal(*_args, **_kwargs):
        raise RuntimeError("journal intentionally unavailable in watchdog unit test")

    monkeypatch.setattr(daemon.duckdb, "connect", _no_journal)

    assert daemon.position_check() is state
    exchange.create_order.assert_not_called()
    exchange.create_market_order.assert_not_called()
    exchange.fapiPrivateDeleteAlgoOrder.assert_not_called()
    assert any("PROT_WATCHDOG_PENDING_OWNER" in line for line in logs)


def test_position_check_expired_lease_uses_original_sl_not_entry_close(monkeypatch):
    import scripts.futures_daemon as daemon
    import scripts.futures_trade_daily as futures_trade_daily

    now = datetime.now(UTC)
    pending = _entry(
        ts=(now - timedelta(seconds=121)).isoformat(),
        tf="15m",
        qty=2.0,
        entry_px=1.0,
        sl_price=1.10,
        tp_price=0.90,
        max_age_seconds=120,
        pre_submit_position_qty=0.0,
    )
    exchange = MagicMock()
    exchange.fapiPrivateV2GetPositionRisk.return_value = []
    exchange.amount_to_precision.side_effect = lambda _symbol, value: str(value)
    exchange.price_to_precision.side_effect = lambda _symbol, value: str(value)
    exchange.create_order.return_value = {"id": "watchdog-original-sl"}
    state = {
        "positions": [
            {
                "symbol": "DOGE/USDT:USDT",
                "side": "short",
                "contracts": 2.0,
                "entryPrice": 1.0,
                "markPrice": 1.05,
                "unrealizedPnl": -0.10,
            }
        ],
        "algo_orders": [],
        "algo_orders_ok": True,
        "regular_orders_ok": True,
        "positions_ok": True,
        "order_scope_ok": True,
        "exchange_state_complete": True,
        "journal_open_position_symbols": [],
        "n_algo_orders": 0,
        "n_open_orders": 0,
        "wallet_balance": 0.0,
        "margin_balance": 0.0,
        "available_balance": 0.0,
        "unrealized_pnl": -0.10,
    }

    monkeypatch.setattr(futures_trade_daily, "get_futures_exchange", lambda: exchange)
    monkeypatch.setattr(futures_trade_daily, "fetch_futures_state", lambda _ex: state)
    monkeypatch.setattr(daemon, "_read_pending_retry_entries", lambda: ([pending], None))
    monkeypatch.setattr(daemon, "_pyramid_positions", {})
    monkeypatch.setattr(daemon, "log", lambda _message: None)

    def _no_journal(*_args, **_kwargs):
        raise RuntimeError("journal intentionally unavailable in watchdog unit test")

    monkeypatch.setattr(daemon.duckdb, "connect", _no_journal)

    assert daemon.position_check() is state
    exchange.create_market_order.assert_not_called()
    assert exchange.create_order.call_count == 1
    call = exchange.create_order.call_args.kwargs
    assert call["type"] == "STOP_MARKET"
    assert float(call["params"]["stopPrice"]) == pytest.approx(1.10)
    assert float(call["amount"]) == pytest.approx(2.0)


def test_reconcile_only_terminal_no_fill_requires_two_confirmations(tmp_path, monkeypatch):
    queue_path = tmp_path / "pending.jsonl"
    entry = _entry(reconcile_only=True, known_order_ids=["ack-no-fill"])
    queue_path.write_text(json.dumps(entry) + "\n", encoding="utf-8")
    monkeypatch.setattr(ppe, "_QUEUE_PATH", queue_path)
    missed: list[str] = []
    monkeypatch.setattr(ppe, "_push_missed", lambda _entry_arg, reason: missed.append(reason))
    monkeypatch.setattr(
        ppe,
        "_try_retry",
        lambda _entry_arg, *, allow_submit=True, on_ack=None: (
            False,
            None,
            "submit_disabled_after_terminal_reconcile",
            object(),
        ),
    )

    first = ppe.process_pending()
    assert first["retry_again"] == 1
    assert json.loads(queue_path.read_text(encoding="utf-8"))["terminal_no_fill_confirmations"] == 1
    second = ppe.process_pending()
    assert second["dropped_terminal"] == 1
    assert not queue_path.exists()
    assert missed and "terminal_no_fill" in missed[0]


def test_finalize_journal_failure_does_not_raise(tmp_path):
    """Journal yazılamasa bile raise YOK (koruma zaten kondu) + missed-audit düşer."""
    ex = FakeExchange()
    order = {"id": "mkt1", "filled": 10.0, "average": 0.155}
    res = ppe._finalize_fill(
        _entry(), order, ex, str(tmp_path / "yok" / "j.duckdb"), str(tmp_path / "i.duckdb")
    )
    assert res["journal"] is False
    assert res["protection"] == "placed"  # koruma yine de kondu
    assert res["finalized"] is False
    assert res["retryable"] is True
    assert res["failure_reason"] == "journal_write_failed_after_protection"


def test_processor_holds_queue_when_journal_write_is_not_finalized(tmp_path, monkeypatch):
    queue_path = tmp_path / "pending.jsonl"
    queue_path.write_text(json.dumps(_entry()) + "\n", encoding="utf-8")
    monkeypatch.setattr(ppe, "_QUEUE_PATH", queue_path)

    def fake_filled_retry(entry_arg, *, allow_submit=True, on_ack=None):
        order = {"id": "filled-journal", "resolved_order_ids": ["filled-journal"]}
        ppe._remember_acknowledged_order(entry_arg, order)
        if on_ack is not None:
            on_ack(entry_arg, order)
        return True, order, "resolved_from_existing_fill", object()

    monkeypatch.setattr(ppe, "_try_retry", fake_filled_retry)
    monkeypatch.setattr(
        ppe,
        "_finalize_fill",
        lambda *_args, **_kwargs: {
            "verified": True,
            "finalized": False,
            "retryable": True,
            "protection": "placed",
            "journal": False,
            "failure_reason": "journal_write_failed_after_protection",
            "fill_qty": 2.0,
            "avg_px": 100.0,
        },
    )

    stats = ppe.process_pending()

    assert stats["success"] == 0
    assert stats["retry_again"] == 1
    persisted = json.loads(queue_path.read_text(encoding="utf-8"))
    assert persisted["last_retry_reason"] == "journal_write_failed_after_protection"


def test_finalize_journal_replay_is_atomic_and_idempotent(tmp_path, monkeypatch):
    """A crash after journal COMMIT cannot duplicate the signal/protection rows."""
    import scripts.futures_trade_daily as futures_trade_daily

    journal = tmp_path / "journal.duckdb"
    _init_journal(journal)
    monkeypatch.setattr(
        futures_trade_daily,
        "place_protection_orders",
        lambda *_args, **_kwargs: {
            "status": "placed",
            "mode": "multi_target",
            "tp_price": 101.0,
            "tp2_price": 102.0,
            "sl_price": 99.0,
            "tp_order_id": "tp-1",
            "tp2_order_id": "tp-2",
            "sl_order_id": "sl-1",
        },
    )
    entry = _entry(ts="2026-07-11T12:00:00+00:00", qty=2.0)
    order = {"id": "market-1", "status": "closed", "filled": 2.0, "average": 100.0}

    first = ppe._finalize_fill(
        entry, order, FakeExchange(), str(journal), str(tmp_path / "idem.duckdb")
    )
    second = ppe._finalize_fill(
        entry, order, FakeExchange(), str(journal), str(tmp_path / "idem.duckdb")
    )

    assert first["finalized"] is True
    assert second["finalized"] is True
    assert first["sig_id"] == second["sig_id"]
    with duckdb.connect(str(journal), read_only=True) as connection:
        assert connection.execute("SELECT count(*) FROM futures_signals").fetchone()[0] == 1
        assert (
            connection.execute("SELECT count(*) FROM futures_protection_orders").fetchone()[0] == 1
        )


def test_side_mapping_and_source_pins():
    assert ppe._SIDE_TO_ORDER["long"] == "buy"
    assert ppe._SIDE_TO_ORDER["short"] == "sell"
    src = (ROOT / "scripts" / "process_pending_entries.py").read_text(encoding="utf-8")
    assert "get_futures_exchange" in src
    assert 'os.environ.get("PA_BINANCE_API_KEY"' not in src  # hayalet env gitti
    daemon_src = (ROOT / "scripts" / "futures_daemon.py").read_text(encoding="utf-8")
    assert '"journal_db": str(JOURNAL)' in daemon_src  # kuyruk kendini-tarifler
    submit_segment = daemon_src.split("EntrySubmitPrepared", 1)[1].split("# Entry truth sırası", 1)[
        0
    ]
    assert "_entry_wal_line = _enqueue_pending_retry" in submit_segment
    assert submit_segment.index("_entry_wal_line = _enqueue_pending_retry") < submit_segment.index(
        "_ex_submit.create_market_order("
    )
    assert '"reconcile_only": True' in daemon_src
    assert 'with open(_pending_path, "a"' not in daemon_src
    scheduler_src = (ROOT / "src/price_action/orchestrator/scheduler.py").read_text(
        encoding="utf-8"
    )
    pending_job = scheduler_src.split("async def _job_process_pending_entries", 1)[1].split(
        "async def ", 1
    )[0]
    assert "timeout=55" in pending_job


def test_existing_symbol_gate_rejects_only_owned_symbol():
    import scripts.futures_daemon as daemon

    positions = [
        {"symbol": "DOGE/USDT:USDT", "contracts": 2.0},
        {"symbol": "BTC/USDT:USDT", "contracts": 0.0},
    ]
    assert daemon._has_existing_symbol_position(positions, "DOGE/USDT") is True
    assert daemon._has_existing_symbol_position(positions, "BTC/USDT") is False
    assert daemon._has_existing_symbol_position(positions, "XRP/USDT") is False


class _ProtectionReplayExchange:
    def __init__(self, *, side="short", qty=2.0, entry=100.0, update_ms=1.0):
        self.side = side
        self.qty = qty
        self.entry = entry
        self.update_ms = update_ms
        self.existing: dict[str, dict] = {}
        self.created: list[str] = []
        self.fail_tp2_once = False

    def amount_to_precision(self, _symbol, value):
        return str(float(value))

    def price_to_precision(self, _symbol, value):
        return str(float(value))

    def fetch_positions(self, _symbols):
        signed = self.qty if self.side == "long" else -self.qty
        return [
            {
                "symbol": "DOGE/USDT:USDT",
                "side": self.side,
                "contracts": self.qty,
                "entryPrice": self.entry,
                "info": {
                    "symbol": "DOGEUSDT",
                    "positionAmt": str(signed),
                    "entryPrice": str(self.entry),
                    "updateTime": str(self.update_ms),
                },
            }
        ]

    def fetch_order(self, _order_id, _symbol, params=None):
        client_id = str((params or {}).get("origClientOrderId") or "")
        if client_id in self.existing:
            return dict(self.existing[client_id])
        raise Exception("OrderNotFound")

    def create_order(self, *, symbol, type, side, amount, params):
        client_id = str(params["newClientOrderId"])
        self.created.append(client_id)
        if client_id.endswith("tp2") and self.fail_tp2_once:
            self.fail_tp2_once = False
            raise TimeoutError("tp2 ACK timeout")
        order = {
            "id": f"order-{len(self.existing) + 1}",
            "status": "open",
            "clientOrderId": client_id,
            "type": type,
            "side": side,
            "amount": amount,
            "triggerPrice": float(params["stopPrice"]),
            "reduceOnly": True,
            "symbol": symbol,
        }
        self.existing[client_id] = order
        return dict(order)


def _protection_finalize_work(tmp_path, exchange):
    import scripts.futures_daemon as daemon
    import scripts.futures_trade_daily as futures_trade_daily

    tmp_path.mkdir(parents=True, exist_ok=True)
    journal = tmp_path / "journal.duckdb"
    idem = tmp_path / "idem.duckdb"
    _init_journal(journal)
    sig = {
        "symbol": "DOGE/USDT",
        "strategy": "vsa",
        "side": "short",
        "sl_price": 105.0,
        "tp_price": 90.0,
        "confluence": 0.8,
        "bar_close_ts": datetime.now(UTC).isoformat(),
    }
    plan = futures_trade_daily.build_protection_plan(
        exchange,
        symbol=sig["symbol"],
        side=sig["side"],
        qty=2.0,
        tp_price=90.0,
        sl_price=105.0,
        entry_price=100.0,
        protection_key="PA_entry_protection",
    )
    work = daemon._build_protection_finalize_entry(
        sig,
        exchange=exchange,
        client_order_id="PA_entry_protection",
        order={"id": "entry-order"},
        fill_method="market_fallback",
        entry_execution_evidence={
            "schema_version": 1,
            "expected_price": 100.0,
            "realized_price": 100.0,
            "quantity": 2.0,
            "notional_usdt": 200.0,
            "fee_usdt": None,
            "fee_source": "unavailable",
            "is_maker": False,
            "order_type": "market",
            "maker_quantity": 0.0,
            "maker_notional_usdt": 0.0,
            "fill_method": "market_fallback",
            "exchange_order_id": "entry-order",
            "order_ids": ["entry-order"],
        },
        fill_qty=2.0,
        fill_price=100.0,
        fill_notional=200.0,
        fill_source="exchange_user_trades",
        leverage=1,
        signal_id="signal-protect-1",
        protection_id="protect-row-1",
        protection_plan=plan,
        known_order_ids=["entry-order"],
    )
    work["journal_db"] = str(journal)
    work["idempotency_db"] = str(idem)
    work["slippage_db"] = str(tmp_path / "fills.duckdb")
    exchange.update_ms = work["position_generation"]["verified_at_ms"] - 1
    return work, journal, idem


def test_protection_wal_is_fsynced_before_sl_and_wal_failure_attempts_only_sl(
    tmp_path, monkeypatch
):
    import scripts.futures_daemon as daemon
    import scripts.process_pending_entries as pending

    exchange = _ProtectionReplayExchange()
    work, _, _ = _protection_finalize_work(tmp_path, exchange)
    queue = tmp_path / "protection.jsonl"
    events: list[str] = []
    original_append = pending.append_pending_entry

    def observed_append(path, entry):
        events.append("wal_fsynced")
        return original_append(path, entry)

    original_create = exchange.create_order

    def observed_create(**kwargs):
        events.append(str(kwargs["params"]["newClientOrderId"])[-3:])
        return original_create(**kwargs)

    monkeypatch.setattr(pending, "append_pending_entry", observed_append)
    exchange.create_order = observed_create
    result, persisted, error = daemon._execute_protection_with_wal(exchange, work, queue_path=queue)

    assert error is None and persisted is True
    assert result["status"] == "placed"
    assert events[0] == "wal_fsynced"
    assert events[1].endswith("sl")

    failed_exchange = _ProtectionReplayExchange()
    failed_work, _, _ = _protection_finalize_work(tmp_path / "failed", failed_exchange)
    monkeypatch.setattr(
        pending,
        "append_pending_entry",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("disk full")),
    )
    result, persisted, error = daemon._execute_protection_with_wal(
        failed_exchange, failed_work, queue_path=tmp_path / "unwritten.jsonl"
    )
    assert persisted is False and "disk full" in str(error)
    assert result["status"] == "sl_placed_only"
    assert len(failed_exchange.created) == 1
    assert failed_exchange.created[0].endswith("sl")


def test_protection_finalize_restart_reconciles_partial_plan_and_journals_once(
    tmp_path, monkeypatch
):
    import scripts.futures_trade_daily as futures_trade_daily

    exchange = _ProtectionReplayExchange()
    exchange.fail_tp2_once = True
    work, journal, _ = _protection_finalize_work(tmp_path, exchange)
    protection_queue = tmp_path / "protection.jsonl"
    entry_queue = tmp_path / "entry.jsonl"
    ppe.append_pending_entry(protection_queue, work)
    monkeypatch.setattr(ppe, "_PROTECTION_QUEUE_PATH", protection_queue)
    monkeypatch.setattr(ppe, "_QUEUE_PATH", entry_queue)
    monkeypatch.setattr(futures_trade_daily, "get_futures_exchange", lambda: exchange)

    first = ppe.process_pending()
    assert first["retry_again"] == 1
    assert protection_queue.exists()
    assert exchange.created[0].endswith("sl")
    assert exchange.created[1].endswith("tp1")
    assert exchange.created[2].endswith("tp2")

    pinned_ids = [leg["client_order_id"] for leg in work["protection_plan"]["legs"]]
    monkeypatch.setattr(futures_trade_daily, "TP1_R", 99.0)
    monkeypatch.setattr(futures_trade_daily, "TP2_R", 199.0)
    exchange.amount_to_precision = lambda *_args: (_ for _ in ()).throw(
        AssertionError("pinned replay must not recompute precision")
    )
    second = ppe.process_pending()

    assert second["success"] == 1
    assert not protection_queue.exists()
    assert exchange.created == [*pinned_ids, pinned_ids[-1]]
    con = duckdb.connect(str(journal), read_only=True)
    try:
        assert con.execute("SELECT COUNT(*) FROM futures_signals").fetchone()[0] == 1
        assert con.execute("SELECT COUNT(*) FROM futures_protection_orders").fetchone()[0] == 1
    finally:
        con.close()


def test_protection_generation_uses_one_authoritative_api_and_stale_work_never_mutates(
    tmp_path, monkeypatch
):
    import scripts.futures_daemon as daemon
    import scripts.futures_trade_daily as futures_trade_daily

    exchange = _ProtectionReplayExchange()
    work, journal, _ = _protection_finalize_work(tmp_path, exchange)
    work["bot_name"] = daemon._BOT_NAME
    exchange.fapiPrivateGetPositionRisk = lambda *_args, **_kwargs: (_ for _ in ()).throw(
        AssertionError("raw position API must be fallback-only")
    )
    assert ppe._protection_position_generation_state(exchange, work)[0] == "match"

    exchange.entry = 101.0
    exchange.update_ms = work["position_generation"]["verified_at_ms"] + 60_000
    protection_queue = tmp_path / "stale.jsonl"
    ppe.append_pending_entry(protection_queue, work)
    monkeypatch.setattr(ppe, "_PROTECTION_QUEUE_PATH", protection_queue)
    monkeypatch.setattr(ppe, "_QUEUE_PATH", tmp_path / "entry.jsonl")
    monkeypatch.setattr(ppe, "_MISSED_PATH", tmp_path / "missed.jsonl")
    monkeypatch.setattr(futures_trade_daily, "get_futures_exchange", lambda: exchange)
    stats = ppe.process_pending()

    assert stats["success"] == 1
    assert not protection_queue.exists()
    assert exchange.created == []
    con = duckdb.connect(str(journal), read_only=True)
    try:
        row = con.execute(
            "SELECT status FROM futures_protection_orders WHERE prot_id=?",
            [work["journal_protection_id"]],
        ).fetchone()
        assert row == ("retired_generation_mismatch",)
    finally:
        con.close()

    expired = dict(work)
    expired["ts"] = (datetime.now(UTC) - timedelta(minutes=10)).isoformat()
    intent = daemon._pending_retry_watchdog_intent(
        expired,
        "DOGE/USDT",
        "short",
        position_contracts=2.0,
        position_entry_price=101.0,
        position_update_time_ms=work["position_generation"]["verified_at_ms"] + 60_000,
        now=datetime.now(UTC),
    )
    assert intent is None

    # Same tick price/qty still cannot impersonate the old generation.
    assert (
        daemon._pending_retry_watchdog_intent(
            expired,
            "DOGE/USDT",
            "short",
            position_contracts=2.0,
            position_entry_price=100.0,
            position_update_time_ms=(work["position_generation"]["verified_at_ms"] + 60_000),
            now=datetime.now(UTC),
        )
        is None
    )

    active_unverifiable = daemon._pending_retry_watchdog_intent(
        work,
        "DOGE/USDT",
        "short",
        position_contracts=2.0,
        position_entry_price=100.0,
        position_update_time_ms=None,
        now=datetime.now(UTC),
    )
    assert active_unverifiable["generation_state"] == "unverifiable"
    assert daemon._pending_retry_watchdog_action(active_unverifiable) == ("hold_processor_owned")
    expired_unverifiable = daemon._pending_retry_watchdog_intent(
        expired,
        "DOGE/USDT",
        "short",
        position_contracts=2.0,
        position_entry_price=100.0,
        position_update_time_ms=None,
        now=datetime.now(UTC),
    )
    assert daemon._pending_retry_watchdog_action(expired_unverifiable) == (
        "watchdog_normal_ignore_intent"
    )

    # A malformed legacy protection-finalize row cannot prove ownership of a
    # later same-symbol position.  Its short active lease remains conservative,
    # but once stale the watchdog ignores the old levels instead of taking them
    # over for the new generation.
    missing_generation = dict(expired)
    missing_generation.pop("position_generation")
    stale_missing = daemon._pending_retry_watchdog_intent(
        missing_generation,
        "DOGE/USDT",
        "short",
        position_contracts=2.0,
        position_entry_price=150.0,
        position_update_time_ms=None,
        now=datetime.now(UTC),
    )
    assert stale_missing["generation_state"] == "unverifiable"
    assert daemon._pending_retry_watchdog_action(stale_missing) == ("watchdog_normal_ignore_intent")

    malformed_generation = dict(work)
    malformed_generation["position_generation"] = dict(work["position_generation"])
    malformed_generation["position_generation"]["initial_quantity"] = True
    active_malformed = daemon._pending_retry_watchdog_intent(
        malformed_generation,
        "DOGE/USDT",
        "short",
        position_contracts=2.0,
        position_entry_price=100.0,
        position_update_time_ms=None,
        now=datetime.now(UTC),
    )
    assert active_malformed["generation_state"] == "unverifiable"
    assert daemon._pending_retry_watchdog_action(active_malformed) == ("hold_processor_owned")


def test_precision_zero_partial_qty_downgrades_without_blocking_sl():
    import scripts.futures_trade_daily as futures_trade_daily

    exchange = _ProtectionReplayExchange()

    def coarse_amount(_symbol, value):
        return "1" if float(value) >= 1.0 else "0"

    exchange.amount_to_precision = coarse_amount
    plan = futures_trade_daily.build_protection_plan(
        exchange,
        symbol="DOGE/USDT",
        side="long",
        qty=1.0,
        tp_price=110.0,
        sl_price=95.0,
        entry_price=100.0,
        protection_key="PA_small_position",
    )
    result = futures_trade_daily.execute_protection_plan(exchange, plan)

    assert plan["mode"] == "single_target"
    assert [leg["name"] for leg in plan["legs"]] == ["sl", "tp"]
    assert result["status"] == "placed"
    assert exchange.created[0].endswith("sl")


def test_flat_before_replay_journals_execution_and_idempotency_exactly_once(tmp_path, monkeypatch):
    import scripts.futures_trade_daily as futures_trade_daily

    exchange = _ProtectionReplayExchange()
    work, journal, _ = _protection_finalize_work(tmp_path, exchange)
    exchange.qty = 0.0
    queue = tmp_path / "flat.jsonl"
    ppe.append_pending_entry(queue, work)
    monkeypatch.setattr(ppe, "_PROTECTION_QUEUE_PATH", queue)
    monkeypatch.setattr(ppe, "_QUEUE_PATH", tmp_path / "entry.jsonl")
    monkeypatch.setattr(ppe, "_MISSED_PATH", tmp_path / "missed.jsonl")
    monkeypatch.setattr(futures_trade_daily, "get_futures_exchange", lambda: exchange)

    first = ppe.process_pending()
    assert first["success"] == 1
    assert not queue.exists()
    assert exchange.created == []

    # Simulate a crash after durable DB commits but before queue removal.
    ppe.append_pending_entry(queue, work)
    second = ppe.process_pending()
    assert second["success"] == 1
    assert not queue.exists()
    assert exchange.created == []

    with duckdb.connect(str(journal), read_only=True) as con:
        assert con.execute("SELECT COUNT(*) FROM futures_signals").fetchone()[0] == 1
        assert con.execute("SELECT COUNT(*) FROM futures_protection_orders").fetchone()[0] == 1
        assert con.execute("SELECT status FROM futures_protection_orders").fetchone() == (
            "retired_flat",
        )
    with duckdb.connect(work["slippage_db"], read_only=True) as con:
        assert con.execute("SELECT COUNT(*) FROM fills").fetchone()[0] == 1


def test_remove_pending_entry_raises_when_exact_and_identity_are_missing(tmp_path):
    queue = tmp_path / "pending.jsonl"
    existing = _entry(client_order_id="PA_other", ts="2026-07-11T00:00:00+00:00")
    ppe.append_pending_entry(queue, existing)
    missing = _entry(client_order_id="PA_missing", ts="2026-07-11T00:00:01+00:00")

    with pytest.raises(RuntimeError, match="identity missing or ambiguous"):
        ppe.remove_pending_entry(queue, json.dumps(missing, default=str))

    assert json.loads(queue.read_text(encoding="utf-8")) == existing


def test_remove_pending_entry_accepts_one_rewritten_identity(tmp_path):
    queue = tmp_path / "pending.jsonl"
    original = _entry(client_order_id="PA_race", ts="2026-07-11T00:00:00+00:00")
    original_line = ppe.append_pending_entry(queue, original)
    rewritten = {
        **original,
        "reconcile_only": True,
        "entry_submit_allowed": False,
        "no_submit_reason": "processor_rewrite",
    }
    ppe._persist_ack_transition(queue, original_line, rewritten)

    ppe.remove_pending_entry(queue, original_line)

    assert not queue.exists()


def test_verified_fill_transition_is_no_submit_before_cleanup(tmp_path):
    queue = tmp_path / "pending.jsonl"
    entry = _entry(
        client_order_id="PA_handoff",
        ts="2026-07-11T00:00:00+00:00",
        entry_submit_allowed=True,
    )
    line = ppe.append_pending_entry(queue, entry)

    transitioned_line = daemon._transition_pending_retry_to_no_submit(
        entry,
        line,
        path=queue,
        reason="verified_fill_protection_handoff",
        updates={"known_order_ids": ["order-1"]},
    )

    durable = json.loads(queue.read_text(encoding="utf-8"))
    assert json.loads(transitioned_line) == durable
    assert durable["entry_submit_allowed"] is False
    assert durable["reconcile_only"] is True
    assert durable["known_order_ids"] == ["order-1"]
    # A crash/remove failure here leaves a reconcile-only row, never a fresh submit owner.
    assert queue.exists()
