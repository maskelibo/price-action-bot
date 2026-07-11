"""Private REST scope reductions and UNKNOWN fail-closed contracts."""

from __future__ import annotations

import json
from pathlib import Path

import duckdb

from scripts import futures_daemon as daemon
from scripts import futures_trade_daily as ftd


def _scope_journal(path: Path) -> Path:
    con = duckdb.connect(str(path))
    try:
        con.execute("CREATE TABLE futures_protection_orders(symbol VARCHAR, status VARCHAR)")
        con.execute(
            "CREATE TABLE futures_signals(signal_id VARCHAR, symbol VARCHAR, status VARCHAR)"
        )
        con.execute("CREATE TABLE futures_trades_closed(trade_id VARCHAR)")
        con.execute("INSERT INTO futures_protection_orders VALUES ('BTC/USDT', 'placed')")
        con.execute("INSERT INTO futures_protection_orders VALUES ('XRP/USDT', 'filled')")
        con.execute("INSERT INTO futures_signals VALUES ('open-zec', 'ZEC/USDT', 'filled')")
        con.execute("INSERT INTO futures_signals VALUES ('closed-dot', 'DOT/USDT', 'filled')")
        con.execute("INSERT INTO futures_trades_closed VALUES ('closed-dot')")
    finally:
        con.close()
    return path


class _ScopedExchange:
    def __init__(self) -> None:
        self.regular_calls: list[dict] = []
        self.algo_calls: list[dict] = []

    def fapiPrivateV2GetAccount(self):  # noqa: N802
        return {
            "totalWalletBalance": "5000",
            "totalUnrealizedProfit": "5",
            "totalMarginBalance": "5005",
            "availableBalance": "4900",
            "totalInitialMargin": "100",
        }

    def fetch_positions(self):
        return [{"symbol": "SOL/USDT:USDT", "contracts": 2.0}]

    def fapiPrivateGetOpenOrders(self, params):  # noqa: N802
        assert params and set(params) == {"symbol"}
        self.regular_calls.append(dict(params))
        return [{"symbol": params["symbol"], "orderId": f"r-{params['symbol']}"}]

    def fapiPrivateGetOpenAlgoOrders(self, params):  # noqa: N802
        assert params and set(params) == {"symbol"}
        self.algo_calls.append(dict(params))
        return {
            "orders": [{"symbol": params["symbol"], "algoId": f"a-{params['symbol']}"}]
        }


def test_state_uses_only_symbol_scoped_order_reads(tmp_path: Path) -> None:
    journal = _scope_journal(tmp_path / "journal.duckdb")
    pending = tmp_path / "pending.jsonl"
    protection_queue = tmp_path / "protection.jsonl"
    pending.write_text(json.dumps({"symbol": "ETH/USDT"}) + "\n", encoding="utf-8")
    protection_queue.write_text(
        json.dumps({"symbol": "AAVE/USDT"}) + "\n", encoding="utf-8"
    )
    exchange = _ScopedExchange()

    state = ftd.fetch_futures_state(
        exchange,
        journal_path=journal,
        pending_queue_path=pending,
        protection_queue_path=protection_queue,
    )

    assert exchange.regular_calls == [{"symbol": "ETHUSDT"}]
    assert exchange.algo_calls == [
        {"symbol": "AAVEUSDT"},
        {"symbol": "BTCUSDT"},
        {"symbol": "ETHUSDT"},
        {"symbol": "SOLUSDT"},
        {"symbol": "ZECUSDT"},
    ]
    assert state["regular_order_scope_symbols"] == ["ETHUSDT"]
    assert state["algo_order_scope_symbols"] == [
        "AAVEUSDT",
        "BTCUSDT",
        "ETHUSDT",
        "SOLUSDT",
        "ZECUSDT",
    ]
    assert state["journal_open_position_symbols"] == ["ZECUSDT"]
    assert state["exchange_state_complete"] is True
    assert state["orders_state"] == "ok"


class _NoOrderReadExchange(_ScopedExchange):
    def fapiPrivateGetOpenOrders(self, params):  # noqa: N802
        raise AssertionError(f"regular order endpoint must not run: {params}")

    def fapiPrivateGetOpenAlgoOrders(self, params):  # noqa: N802
        raise AssertionError(f"algo order endpoint must not run: {params}")


def test_missing_journal_makes_order_state_unknown_without_order_http(tmp_path: Path) -> None:
    state = ftd.fetch_futures_state(
        _NoOrderReadExchange(),
        journal_path=tmp_path / "missing.duckdb",
        pending_queue_path=tmp_path / "missing-pending.jsonl",
        protection_queue_path=tmp_path / "missing-protection.jsonl",
    )

    assert state["order_scope_ok"] is False
    assert state["regular_orders_ok"] is False
    assert state["algo_orders_ok"] is False
    assert state["exchange_state_complete"] is False
    assert state["orders_state"] == "unknown"
    assert "FileNotFoundError" in str(state["order_scope_error"])
    assert state["n_open_orders"] == 0


def test_malformed_queue_makes_order_state_unknown_without_order_http(tmp_path: Path) -> None:
    journal = _scope_journal(tmp_path / "journal.duckdb")
    pending = tmp_path / "pending.jsonl"
    pending.write_text("{not-json}\n", encoding="utf-8")

    state = ftd.fetch_futures_state(
        _NoOrderReadExchange(),
        journal_path=journal,
        pending_queue_path=pending,
        protection_queue_path=tmp_path / "missing-protection.jsonl",
    )

    assert state["order_scope_ok"] is False
    assert state["exchange_state_complete"] is False
    assert state["orders_state"] == "unknown"
    assert "ValueError" in str(state["order_scope_error"])


def test_partial_or_identity_less_order_response_is_unknown(tmp_path: Path) -> None:
    journal = _scope_journal(tmp_path / "journal.duckdb")

    class _IdentityLessExchange(_ScopedExchange):
        def fapiPrivateGetOpenAlgoOrders(self, params):  # noqa: N802
            self.algo_calls.append(dict(params))
            return [{"symbol": params["symbol"], "orderType": "STOP_MARKET"}]

    state = ftd.fetch_futures_state(
        _IdentityLessExchange(),
        journal_path=journal,
        pending_queue_path=tmp_path / "no-pending.jsonl",
        protection_queue_path=tmp_path / "no-protection.jsonl",
    )

    assert state["algo_orders_ok"] is False
    assert state["exchange_state_complete"] is False
    assert state["orders_state"] == "unknown"
    assert state["n_algo_orders"] == 0


def test_second_position_read_has_real_orphan_candidate_gate() -> None:
    owned_orders = [
        {"symbol": "BTCUSDT", "algoId": "a-1"},
        {"symbol": "ETHUSDT", "algoId": "a-2"},
    ]
    assert daemon._orphan_confirmation_candidates(
        owned_orders,
        {"BTCUSDT"},
        {"ETHUSDT"},
    ) == set()

    assert daemon._orphan_confirmation_candidates(
        [*owned_orders, {"symbol": "SOLUSDT", "algoId": "a-3"}],
        {"BTCUSDT"},
        {"ETHUSDT"},
    ) == {"SOLUSDT"}


def test_position_risk_endpoint_is_not_called_without_orphan_candidate() -> None:
    class _Exchange:
        def fapiPrivateV2GetPositionRisk(self):  # noqa: N802
            raise AssertionError("positionRisk must not run without a real candidate")

    assert daemon._fresh_orphan_position_symbols(
        _Exchange(),
        set(),
        {"BTCUSDT"},
    ) == {"BTCUSDT"}


def test_position_risk_endpoint_confirms_only_after_candidate_exists() -> None:
    class _Exchange:
        calls = 0

        def fapiPrivateV2GetPositionRisk(self):  # noqa: N802
            self.calls += 1
            return [{"symbol": "SOLUSDT", "positionAmt": "2"}]

    exchange = _Exchange()
    assert daemon._fresh_orphan_position_symbols(
        exchange,
        {"SOLUSDT"},
        set(),
    ) == {"SOLUSDT"}
    assert exchange.calls == 1


def test_rate_budget_headers_are_case_insensitive_and_secret_free() -> None:
    class _Exchange:
        def __init__(self) -> None:
            self.last_response_headers = {
                "X-MBX-USED-WEIGHT-1M": "123",
                "x-MbX-OrDeR-CoUnT-10S": "4.0",
                "X-MBX-ORDER-COUNT-1m": 5,
                "x-mbx-order-count-1d": "6",
                "Authorization": "must-never-be-logged",
                "X-MBX-APIKEY": "also-secret",
            }

    line = daemon._rate_budget_log_line(_Exchange())

    assert line == (
        "RATE_BUDGET: used_weight_1m=123 order_count_10s=4 "
        "order_count_1m=5 order_count_1d=6"
    )
    assert "must-never" not in line
    assert "also-secret" not in line


def test_rate_budget_invalid_nonfinite_or_missing_values_are_unknown() -> None:
    class _Exchange:
        def __init__(self) -> None:
            self.last_response_headers = {
                "x-mbx-used-weight-1m": "nan",
                "x-mbx-order-count-10s": "inf",
                "x-mbx-order-count-1m": "-1",
                "x-mbx-order-count-1d": "1.5",
            }

    assert daemon._rate_budget_log_line(_Exchange()) == (
        "RATE_BUDGET: used_weight_1m=UNKNOWN order_count_10s=UNKNOWN "
        "order_count_1m=UNKNOWN order_count_1d=UNKNOWN"
    )
    assert daemon._rate_budget_log_line(None) == (
        "RATE_BUDGET: used_weight_1m=UNKNOWN order_count_10s=UNKNOWN "
        "order_count_1m=UNKNOWN order_count_1d=UNKNOWN"
    )


def test_registered_main_exchange_is_reused_without_factory(monkeypatch) -> None:
    sentinel = object()
    monkeypatch.setattr(daemon, "_DAEMON_PRIVATE_EXCHANGE", sentinel)

    import scripts.futures_trade_daily as futures_trade_daily

    monkeypatch.setattr(
        futures_trade_daily,
        "get_futures_exchange",
        lambda: (_ for _ in ()).throw(AssertionError("factory must not run")),
    )
    assert daemon._get_daemon_exchange() is sentinel


def test_entry_trust_requires_complete_order_scope_and_consistent_positions() -> None:
    complete_flat = {
        "exchange_state_complete": True,
        "positions_ok": True,
        "positions": [],
        "total_initial_margin": 0,
    }
    assert ftd._futures_state_entry_trusted(complete_flat) is True
    assert ftd._futures_state_entry_trusted(
        {**complete_flat, "exchange_state_complete": False}
    ) is False
    assert ftd._futures_state_entry_trusted(
        {**complete_flat, "order_scope_ok": False, "exchange_state_complete": False}
    ) is False
    assert ftd._futures_state_entry_trusted(
        {**complete_flat, "total_initial_margin": 1}
    ) is False
    assert ftd._futures_state_entry_trusted(
        {**complete_flat, "total_initial_margin": "nan"}
    ) is False


def test_position_check_skips_all_mutations_when_order_scope_is_unknown(monkeypatch) -> None:
    class _Exchange:
        def fapiPrivateV2GetPositionRisk(self):  # noqa: N802
            raise AssertionError("confirmation mutation path must be skipped")

        def fapiPrivateDeleteAlgoOrder(self, _params):  # noqa: N802
            raise AssertionError("order cancellation must be skipped")

        def create_order(self, **_kwargs):
            raise AssertionError("protection mutation must be skipped")

    state = {
        "positions": [],
        "algo_orders": [],
        "positions_ok": True,
        "regular_orders_ok": False,
        "algo_orders_ok": False,
        "order_scope_ok": False,
        "order_scope_error": "ValueError: malformed queue",
        "exchange_state_complete": False,
        "n_positions": 0,
        "n_open_orders": 0,
        "n_algo_orders": 0,
        "wallet_balance": 5000.0,
        "margin_balance": 5000.0,
        "available_balance": 5000.0,
        "unrealized_pnl": 0.0,
    }
    exchange = _Exchange()
    monkeypatch.setattr(daemon, "_DAEMON_PRIVATE_EXCHANGE", None)
    monkeypatch.setattr(ftd, "get_futures_exchange", lambda: exchange)
    monkeypatch.setattr(ftd, "fetch_futures_state", lambda _exchange: state)
    messages: list[str] = []
    monkeypatch.setattr(daemon, "log", messages.append)

    assert daemon.position_check() is state
    assert any("exchange state UNKNOWN" in message for message in messages)
