"""Crash-complete TP1/TP2/SL execution evidence lifecycle."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import duckdb
import pytest
import scripts.futures_daemon as daemon

from price_action.execution.slippage_tracker import SlippageTracker
from price_action.execution.trade_journal import TradeJournal


class _ExitExchange:
    def __init__(self, rows_by_order: dict[str, list[dict]]) -> None:
        self.rows_by_order = rows_by_order

    def fapiPrivateGetUserTrades(self, params):  # noqa: N802 - CCXT API surface
        return list(self.rows_by_order.get(str(params["orderId"]), []))


def _trade(order_id: str, *, qty: float, price: float, fee: float) -> dict:
    return {
        "orderId": int(order_id),
        "price": str(price),
        "qty": str(qty),
        "quoteQty": str(qty * price),
        "commission": str(fee),
        "commissionAsset": "USDT",
        "maker": False,
    }


def _order(
    algo_id: str,
    actual_order_id: str,
    *,
    update_time: int,
    qty: float,
    price: float,
    kind: str,
) -> dict:
    return {
        "algoId": algo_id,
        "actualOrderId": actual_order_id,
        "algoStatus": "FINISHED",
        "updateTime": update_time,
        "actualQuantity": str(qty),
        "avgPrice": str(price),
        "triggerPrice": str(price),
        "orderType": "STOP_MARKET" if kind == "SL" else "TAKE_PROFIT_MARKET",
    }


def _init_journal(path: Path) -> duckdb.DuckDBPyConnection:
    TradeJournal(db_path=str(path))
    con = duckdb.connect(str(path))
    con.execute(
        """CREATE TABLE IF NOT EXISTS futures_signals (
               signal_id VARCHAR PRIMARY KEY, ts TIMESTAMP, symbol VARCHAR,
               strategy VARCHAR, side VARCHAR, sl_price DOUBLE, tp_price DOUBLE,
               confluence DOUBLE, leverage INTEGER, status VARCHAR,
               order_id VARCHAR, fill_price DOUBLE, fill_qty DOUBLE,
               notional_usdt DOUBLE, margin_usdt DOUBLE, notes VARCHAR
           )"""
    )
    con.execute(
        """CREATE TABLE IF NOT EXISTS futures_protection_orders (
               prot_id VARCHAR PRIMARY KEY, ts TIMESTAMP, signal_id VARCHAR,
               symbol VARCHAR, side VARCHAR, qty DOUBLE, tp_price DOUBLE,
               sl_price DOUBLE, tp_order_id VARCHAR, sl_order_id VARCHAR,
               status VARCHAR, notes VARCHAR
           )"""
    )
    con.execute(
        """INSERT INTO futures_signals VALUES
           ('sig-1', ?, 'BTC/USDT', 'vsa', 'long', 90, 120, 1, 1,
            'filled', 'entry-1', 100, 10, 1000, 1000, '')""",
        [datetime(2026, 7, 11, tzinfo=UTC)],
    )
    con.execute(
        """INSERT INTO futures_protection_orders VALUES
           ('prot-1', ?, 'sig-1', 'BTC/USDT', 'long', 10, 110, 90,
            '101', '303', 'placed', 'tp2_id=202')""",
        [datetime(2026, 7, 11, tzinfo=UTC)],
    )
    return con


def _process_candidates(
    con,
    exchange,
    tracker,
    journal: Path,
    candidates: list[tuple[dict, str]],
    *,
    position_flat: bool,
) -> None:
    for index, (order, kind) in enumerate(candidates):
        assert daemon._process_protection_terminal_event(
            con=con,
            exchange=exchange,
            prot_id="prot-1",
            symbol="BTC/USDT",
            symbol_id="BTCUSDT",
            triggered_order=order,
            triggered_kind=kind,
            position_flat=position_flat,
            is_last_candidate=index == len(candidates) - 1,
            journal_path=journal,
            tracker=tracker,
            income_fetcher=lambda *_args: None,
        )


def test_same_poll_tp1_and_tp2_are_each_persisted_exactly_once(tmp_path):
    journal = tmp_path / "journal.duckdb"
    con = _init_journal(journal)
    tracker = SlippageTracker(tmp_path / "fills.duckdb")
    tp1 = _order("101", "701", update_time=1_000, qty=3, price=110, kind="TP1")
    tp2 = _order("202", "702", update_time=2_000, qty=3, price=115, kind="TP2")
    exchange = _ExitExchange(
        {
            "701": [_trade("701", qty=3, price=110, fee=0.10)],
            "702": [_trade("702", qty=3, price=115, fee=0.11)],
        }
    )
    candidates = daemon._protection_terminal_candidates(
        sl_order=None,
        tp1_order=tp1,
        tp2_order=tp2,
    )

    _process_candidates(con, exchange, tracker, journal, candidates, position_flat=False)
    _process_candidates(con, exchange, tracker, journal, candidates, position_flat=False)

    partials = con.execute(
        "SELECT close_reason, qty_closed, exit_price FROM futures_partial_closes ORDER BY ts_close"
    ).fetchall()
    events = con.execute(
        "SELECT kind, quantity, price FROM futures_protection_fill_events ORDER BY terminal_time_ms"
    ).fetchall()
    con.close()
    with duckdb.connect(str(tmp_path / "fills.duckdb"), read_only=True) as fills:
        evidence = fills.execute(
            "SELECT fill_id, quantity, realized_price, fee_usdt FROM fills ORDER BY fill_id"
        ).fetchall()

    assert partials == [("tp1", 3.0, 110.0), ("tp2", 3.0, 115.0)]
    assert events == [("tp1", 3.0, 110.0), ("tp2", 3.0, 115.0)]
    assert evidence == [
        ("prot_prot-1_tp1", 3.0, 110.0, 0.1),
        ("prot_prot-1_tp2", 3.0, 115.0, 0.11),
    ]


def test_same_poll_tp1_tp2_then_sl_preserves_partial_to_full_lifecycle(tmp_path):
    journal = tmp_path / "journal.duckdb"
    con = _init_journal(journal)
    tracker = SlippageTracker(tmp_path / "fills.duckdb")
    tp1 = _order("101", "701", update_time=1_000, qty=3, price=110, kind="TP1")
    tp2 = _order("202", "702", update_time=2_000, qty=3, price=115, kind="TP2")
    sl = _order("303", "703", update_time=3_000, qty=4, price=105, kind="SL")
    exchange = _ExitExchange(
        {
            "701": [_trade("701", qty=3, price=110, fee=0.10)],
            "702": [_trade("702", qty=3, price=115, fee=0.11)],
            "703": [_trade("703", qty=4, price=105, fee=0.12)],
        }
    )
    candidates = daemon._protection_terminal_candidates(
        sl_order=sl,
        tp1_order=tp1,
        tp2_order=tp2,
    )

    _process_candidates(con, exchange, tracker, journal, candidates, position_flat=True)
    _process_candidates(con, exchange, tracker, journal, candidates, position_flat=True)

    assert con.execute(
        "SELECT close_reason, qty_closed FROM futures_partial_closes ORDER BY ts_close"
    ).fetchall() == [("tp1", 3.0), ("tp2", 3.0)]
    assert con.execute(
        "SELECT close_reason, qty, exit_price FROM futures_trades_closed"
    ).fetchall() == [("sl", 4.0, 105.0)]
    assert con.execute("SELECT COUNT(*) FROM futures_protection_fill_events").fetchone()[0] == 3
    assert daemon._protection_retirement_ready(
        position_flat=True,
        events_ok=True,
        unprocessed_event_count=0,
        trade_closed=True,
        has_terminal_state=True,
    )
    con.close()


def test_unverified_or_failed_evidence_never_journals_or_marks_processed_then_replays(
    tmp_path,
):
    journal = tmp_path / "journal.duckdb"
    con = _init_journal(journal)
    tracker = SlippageTracker(tmp_path / "fills.duckdb")
    tp1 = _order("101", "", update_time=1_000, qty=3, price=110, kind="TP1")
    tp1.pop("avgPrice")
    tp1.pop("actualQuantity")
    exchange = _ExitExchange({})

    assert (
        daemon._process_protection_terminal_event(
            con=con,
            exchange=exchange,
            prot_id="prot-1",
            symbol="BTC/USDT",
            symbol_id="BTCUSDT",
            triggered_order=tp1,
            triggered_kind="TP1",
            position_flat=False,
            is_last_candidate=True,
            journal_path=journal,
            tracker=tracker,
            income_fetcher=lambda *_args: None,
        )
        is False
    )
    assert con.execute("SELECT COUNT(*) FROM futures_partial_closes").fetchone()[0] == 0
    assert con.execute("SELECT COUNT(*) FROM futures_protection_fill_events").fetchone()[0] == 0
    assert con.execute(
        "SELECT status FROM futures_protection_orders WHERE prot_id='prot-1'"
    ).fetchone() == ("placed",)
    assert not daemon._protection_retirement_ready(
        position_flat=True,
        events_ok=False,
        unprocessed_event_count=1,
        trade_closed=False,
        has_terminal_state=True,
    )

    tp1["actualOrderId"] = "701"
    exchange.rows_by_order["701"] = [_trade("701", qty=3, price=110, fee=0.10)]
    assert daemon._process_protection_terminal_event(
        con=con,
        exchange=exchange,
        prot_id="prot-1",
        symbol="BTC/USDT",
        symbol_id="BTCUSDT",
        triggered_order=tp1,
        triggered_kind="TP1",
        position_flat=False,
        is_last_candidate=True,
        journal_path=journal,
        tracker=tracker,
        income_fetcher=lambda *_args: None,
    )
    assert con.execute("SELECT COUNT(*) FROM futures_partial_closes").fetchone()[0] == 1
    assert con.execute("SELECT COUNT(*) FROM futures_protection_fill_events").fetchone()[0] == 1
    con.close()


def test_tracker_exception_leaves_event_replayable(tmp_path):
    journal = tmp_path / "journal.duckdb"
    con = _init_journal(journal)
    tp1 = _order("101", "701", update_time=1_000, qty=3, price=110, kind="TP1")
    exchange = _ExitExchange({"701": [_trade("701", qty=3, price=110, fee=0.10)]})

    class _FailingTracker:
        def record_fill(self, **_kwargs):
            raise OSError("execution DB unavailable")

    with pytest.raises(OSError, match="execution DB unavailable"):
        daemon._process_protection_terminal_event(
            con=con,
            exchange=exchange,
            prot_id="prot-1",
            symbol="BTC/USDT",
            symbol_id="BTCUSDT",
            triggered_order=tp1,
            triggered_kind="TP1",
            position_flat=False,
            is_last_candidate=True,
            journal_path=journal,
            tracker=_FailingTracker(),
            income_fetcher=lambda *_args: None,
        )
    assert con.execute("SELECT COUNT(*) FROM futures_partial_closes").fetchone()[0] == 0
    assert con.execute("SELECT COUNT(*) FROM futures_protection_fill_events").fetchone()[0] == 0

    tracker = SlippageTracker(tmp_path / "fills.duckdb")
    assert daemon._process_protection_terminal_event(
        con=con,
        exchange=exchange,
        prot_id="prot-1",
        symbol="BTC/USDT",
        symbol_id="BTCUSDT",
        triggered_order=tp1,
        triggered_kind="TP1",
        position_flat=False,
        is_last_candidate=True,
        journal_path=journal,
        tracker=tracker,
        income_fetcher=lambda *_args: None,
    )
    assert con.execute("SELECT COUNT(*) FROM futures_protection_fill_events").fetchone()[0] == 1
    con.close()


@pytest.mark.parametrize(
    ("kind", "algo_id", "order_id", "qty", "price", "position_flat", "journal_method"),
    [
        ("TP1", "101", "701", 3.0, 110.0, False, "record_partial_close"),
        ("SL", "303", "703", 10.0, 95.0, True, "record_close"),
    ],
)
def test_cross_db_journal_failure_replays_tracker_noop_then_completes_event(
    tmp_path,
    monkeypatch,
    kind,
    algo_id,
    order_id,
    qty,
    price,
    position_flat,
    journal_method,
):
    journal = tmp_path / "journal.duckdb"
    con = _init_journal(journal)
    tracker = SlippageTracker(tmp_path / "fills.duckdb")
    jsonl_writes = []
    monkeypatch.setattr(
        tracker,
        "_write_jsonl",
        lambda *args, **kwargs: jsonl_writes.append((args, kwargs)),
    )
    terminal = _order(
        algo_id,
        order_id,
        update_time=1_000,
        qty=qty,
        price=price,
        kind=kind,
    )
    exchange = _ExitExchange(
        {order_id: [_trade(order_id, qty=qty, price=price, fee=0.10)]}
    )
    original_journal_method = getattr(TradeJournal, journal_method)

    def _fail_journal(*_args, **_kwargs):
        raise OSError("journal write unavailable after tracker commit")

    monkeypatch.setattr(TradeJournal, journal_method, _fail_journal)
    with pytest.raises(OSError, match="journal write unavailable"):
        daemon._process_protection_terminal_event(
            con=con,
            exchange=exchange,
            prot_id="prot-1",
            symbol="BTC/USDT",
            symbol_id="BTCUSDT",
            triggered_order=terminal,
            triggered_kind=kind,
            position_flat=position_flat,
            is_last_candidate=True,
            journal_path=journal,
            tracker=tracker,
            income_fetcher=lambda *_args: None,
        )

    with duckdb.connect(str(tmp_path / "fills.duckdb"), read_only=True) as fills:
        assert fills.execute("SELECT COUNT(*) FROM fills").fetchone()[0] == 1
    assert con.execute("SELECT COUNT(*) FROM futures_protection_fill_events").fetchone()[0] == 0
    assert con.execute("SELECT COUNT(*) FROM futures_partial_closes").fetchone()[0] == 0
    assert con.execute("SELECT COUNT(*) FROM futures_trades_closed").fetchone()[0] == 0
    assert not daemon._protection_retirement_ready(
        position_flat=position_flat,
        events_ok=False,
        unprocessed_event_count=1,
        trade_closed=False,
        has_terminal_state=True,
    )

    monkeypatch.setattr(TradeJournal, journal_method, original_journal_method)
    assert daemon._process_protection_terminal_event(
        con=con,
        exchange=exchange,
        prot_id="prot-1",
        symbol="BTC/USDT",
        symbol_id="BTCUSDT",
        triggered_order=terminal,
        triggered_kind=kind,
        position_flat=position_flat,
        is_last_candidate=True,
        journal_path=journal,
        tracker=tracker,
        income_fetcher=lambda *_args: None,
    )
    assert len(jsonl_writes) == 1
    assert con.execute("SELECT COUNT(*) FROM futures_protection_fill_events").fetchone()[0] == 1
    expected_partial = 1 if journal_method == "record_partial_close" else 0
    expected_final = 1 if journal_method == "record_close" else 0
    assert con.execute("SELECT COUNT(*) FROM futures_partial_closes").fetchone()[0] == (
        expected_partial
    )
    assert con.execute("SELECT COUNT(*) FROM futures_trades_closed").fetchone()[0] == expected_final
    con.close()
