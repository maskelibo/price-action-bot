from __future__ import annotations

import importlib.util
import math
import os
import sys
import types
from datetime import UTC, datetime, timedelta
from pathlib import Path

import duckdb
import pytest

ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "scripts" / "dashboard" / "collect.py"

PNL_KEYS = {
    "ok",
    "error",
    "warnings",
    "net_realized",
    "realized_pnl",
    "commission",
    "funding",
    "n_closes",
    "clean_net",
    "clean_realized",
    "clean_comm",
    "clean_funding",
    "clean_n",
    "unrealized",
    "wallet",
    "margin",
    "available",
    "total_pnl",
    "total_pnl_pct",
    "start_equity",
    "anchor_tr",
    "clean_tr",
    "positions",
    "pos_notional_total",
    "pos_margin_total",
    "n_pos",
    "n_pos_green",
    "positions_ok",
    "sym_attribution",
    "all_attribution",
    "closed_stats",
    "closed_trades",
    "daily_pnl",
    "recent_closes",
}


def _load_module():
    spec = importlib.util.spec_from_file_location("pa_dashboard_collect_local_test", MODULE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _deny_exchange_constructor(monkeypatch) -> None:
    fake = types.ModuleType("scripts.futures_trade_daily")

    def forbidden():
        raise AssertionError("dashboard collector must not construct an exchange client")

    fake.get_futures_exchange = forbidden
    monkeypatch.setitem(sys.modules, "scripts.futures_trade_daily", fake)


def _write_journal(root: Path, *, snapshot_ts: datetime | None) -> None:
    path = root / "data" / "futures_journal_v15p2.duckdb"
    path.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(path))
    con.execute(
        """CREATE TABLE futures_equity_snapshots (
               snapshot_id VARCHAR PRIMARY KEY, ts TIMESTAMP, wallet_balance DOUBLE,
               unrealized_pnl DOUBLE, margin_balance DOUBLE, available_balance DOUBLE,
               n_positions INTEGER, n_open_orders INTEGER, notes VARCHAR
           )"""
    )
    con.execute(
        """CREATE TABLE futures_trades_closed (
               trade_id VARCHAR PRIMARY KEY, ts_close TIMESTAMP, sym VARCHAR,
               realized_pnl_usdt DOUBLE
           )"""
    )
    con.execute(
        """CREATE TABLE futures_partial_closes (
               close_id VARCHAR PRIMARY KEY, ts_close TIMESTAMP, sym VARCHAR,
               realized_pnl_usdt DOUBLE
           )"""
    )
    if snapshot_ts is not None:
        con.execute(
            "INSERT INTO futures_equity_snapshots VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                "snap-1",
                snapshot_ts.replace(tzinfo=None),
                5000.0,
                12.0,
                5012.0,
                4200.0,
                1,
                3,
                "15m_bar_g19",
            ],
        )
    con.execute(
        "INSERT INTO futures_trades_closed VALUES (?, ?, ?, ?)",
        ["old-close", datetime(2026, 7, 5, 12, 0), "XLM/USDT", -5.0],
    )
    con.execute(
        "INSERT INTO futures_trades_closed VALUES (?, ?, ?, ?)",
        ["clean-close", datetime(2026, 7, 10, 12, 0), "ZEC/USDT", 20.0],
    )
    con.close()


def _write_fills(root: Path) -> None:
    path = root / "data" / "execution_fills.duckdb"
    con = duckdb.connect(str(path))
    con.execute(
        """CREATE TABLE fills (
               fill_id VARCHAR PRIMARY KEY, ts TIMESTAMP, symbol VARCHAR,
               fee_usdt DOUBLE, fill_role VARCHAR
           )"""
    )
    con.execute(
        "INSERT INTO fills VALUES (?, ?, ?, ?, ?)",
        ["fee-old", datetime(2026, 7, 5, 12, 0), "XLM/USDT", 0.5, "exit"],
    )
    con.execute(
        "INSERT INTO fills VALUES (?, ?, ?, ?, ?)",
        ["fee-clean", datetime(2026, 7, 10, 12, 0), "ZEC/USDT", 1.5, "exit"],
    )
    con.close()


def _write_pos_check(root: Path, *, now: datetime) -> None:
    path = root / "logs" / "futures_daemon_v15p2.log"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "[01:00:00Z] POS_CHECK: 1 pos, 3 algo (TP+SL) | ZEC=L1.500@$500.0000->508.0000(+12.00)\n",
        encoding="utf-8",
    )
    epoch = now.timestamp()
    os.utime(path, (epoch, epoch))


def _prepare(monkeypatch, tmp_path: Path, *, snapshot_ts: datetime | None, now: datetime):
    module = _load_module()
    monkeypatch.setattr(module, "ROOT", tmp_path)
    monkeypatch.setattr(module, "_now_utc", lambda: now)
    _deny_exchange_constructor(monkeypatch)
    _write_journal(tmp_path, snapshot_ts=snapshot_ts)
    _write_fills(tmp_path)
    _write_pos_check(tmp_path, now=now)
    return module


def _update_journal(root: Path, statement: str, params: list[object]) -> None:
    con = duckdb.connect(str(root / "data" / "futures_journal_v15p2.duckdb"))
    try:
        con.execute(statement, params)
    finally:
        con.close()


def _update_fills(root: Path, statement: str, params: list[object]) -> None:
    con = duckdb.connect(str(root / "data" / "execution_fills.duckdb"))
    try:
        con.execute(statement, params)
    finally:
        con.close()


def _replace_pos_check(root: Path, *, now: datetime, line: str) -> None:
    path = root / "logs" / "futures_daemon_v15p2.log"
    path.write_text(line.rstrip() + "\n", encoding="utf-8")
    epoch = now.timestamp()
    os.utime(path, (epoch, epoch))


def _assert_all_floats_finite(value: object) -> None:
    if isinstance(value, float):
        assert math.isfinite(value)
    elif isinstance(value, dict):
        for item in value.values():
            _assert_all_floats_finite(item)
    elif isinstance(value, list):
        for item in value:
            _assert_all_floats_finite(item)


def test_fresh_snapshot_journals_and_pos_log_produce_pnl_without_exchange(
    monkeypatch, tmp_path: Path
) -> None:
    now = datetime(2026, 7, 11, 1, 10, tzinfo=UTC)
    module = _prepare(
        monkeypatch,
        tmp_path,
        snapshot_ts=now - timedelta(minutes=10),
        now=now,
    )

    pnl = module.collect_pnl()

    assert pnl["ok"] is True
    assert pnl["wallet"] == 5000.0
    assert pnl["unrealized"] == 12.0
    assert pnl["total_pnl"] == 49.0
    assert pnl["realized_pnl"] == 15.0
    assert pnl["commission"] == -2.0
    assert pnl["net_realized"] == 15.0
    assert pnl["clean_realized"] == 20.0
    assert pnl["clean_comm"] == -1.5
    assert pnl["clean_net"] == 20.0
    assert pnl["n_pos"] == 1
    assert pnl["positions"][0]["symbol"] == "ZEC"
    assert pnl["positions"][0]["upnl"] == 12.0
    assert pnl["positions"][0]["margin"] is None
    assert pnl["pos_margin_total"] is None
    assert pnl["error"] is None
    assert any("funding geliri" in warning for warning in pnl["warnings"])


def test_stale_snapshot_fails_closed_but_keeps_schema_and_never_calls_exchange(
    monkeypatch, tmp_path: Path
) -> None:
    now = datetime(2026, 7, 11, 1, 10, tzinfo=UTC)
    module = _prepare(
        monkeypatch,
        tmp_path,
        snapshot_ts=now - timedelta(minutes=31),
        now=now,
    )

    pnl = module.collect_pnl()

    assert pnl["ok"] is False
    assert pnl["error"].startswith("STALE: snapshot 31.0 dk eski")
    assert pnl["realized_pnl"] == 15.0
    assert pnl["n_pos"] == 1
    assert pnl["unrealized"] == 12.0
    assert set(pnl) == PNL_KEYS


def test_missing_local_evidence_warns_without_api_fallback(monkeypatch, tmp_path: Path) -> None:
    module = _load_module()
    monkeypatch.setattr(module, "ROOT", tmp_path)
    monkeypatch.setattr(
        module,
        "_now_utc",
        lambda: datetime(2026, 7, 11, 1, 10, tzinfo=UTC),
    )
    _deny_exchange_constructor(monkeypatch)

    pnl = module.collect_pnl()

    assert pnl["ok"] is False
    assert "STALE: snapshot DB yok" in pnl["error"]
    assert "EVIDENCE: journal DB yok" in pnl["error"]
    assert set(pnl) == PNL_KEYS


def test_api_snapshot_top_level_schema_remains_stable(monkeypatch, tmp_path: Path) -> None:
    now = datetime(2026, 7, 11, 1, 10, tzinfo=UTC)
    module = _prepare(
        monkeypatch,
        tmp_path,
        snapshot_ts=now - timedelta(minutes=10),
        now=now,
    )
    monkeypatch.setattr(module, "collect_daemons", lambda: [])
    monkeypatch.setattr(module, "collect_audit", lambda: {"open": 0, "overdue": 0})
    monkeypatch.setattr(module, "collect_research", lambda: {})
    monkeypatch.setattr(module, "collect_worklog", lambda: [])
    monkeypatch.setattr(module, "collect_botstats", lambda: {})
    monkeypatch.setattr(module, "collect_system", lambda: {})

    snapshot = module.collect_all()

    assert set(snapshot) == {
        "generated_utc",
        "generated_tr",
        "pnl",
        "daemons",
        "audit",
        "research",
        "worklog",
        "botstats",
        "system",
        "agents",
        "org",
        "health",
    }
    assert set(snapshot["pnl"]) == PNL_KEYS
    assert snapshot["health"] == "warn"


@pytest.mark.parametrize(
    ("column", "value", "reason"),
    [
        ("wallet_balance", float("nan"), "wallet_balance sonlu sayı değil"),
        ("unrealized_pnl", float("inf"), "unrealized_pnl sonlu sayı değil"),
        ("margin_balance", float("-inf"), "margin_balance sonlu sayı değil"),
        ("n_positions", -1, "n_positions geçersiz sayaç"),
        ("n_open_orders", -2, "n_open_orders geçersiz sayaç"),
    ],
)
def test_snapshot_rejects_nonfinite_numbers_and_negative_counts(
    monkeypatch,
    tmp_path: Path,
    column: str,
    value: object,
    reason: str,
) -> None:
    now = datetime(2026, 7, 11, 1, 10, tzinfo=UTC)
    module = _prepare(
        monkeypatch,
        tmp_path,
        snapshot_ts=now - timedelta(minutes=10),
        now=now,
    )
    _update_journal(
        tmp_path,
        f"UPDATE futures_equity_snapshots SET {column} = ?",
        [value],
    )

    pnl = module.collect_pnl()

    assert pnl["ok"] is False
    assert reason in pnl["error"]
    _assert_all_floats_finite(pnl)


def test_nonfinite_journal_pnl_is_rejected_instead_of_serialized(
    monkeypatch, tmp_path: Path
) -> None:
    now = datetime(2026, 7, 11, 1, 10, tzinfo=UTC)
    module = _prepare(
        monkeypatch,
        tmp_path,
        snapshot_ts=now - timedelta(minutes=10),
        now=now,
    )
    _update_journal(
        tmp_path,
        "UPDATE futures_trades_closed SET realized_pnl_usdt = ? WHERE trade_id = ?",
        [float("nan"), "clean-close"],
    )

    pnl = module.collect_pnl()

    assert pnl["ok"] is False
    assert "realized_pnl_usdt sonlu sayı değil" in pnl["error"]
    _assert_all_floats_finite(pnl)


def test_nonfinite_fill_fee_is_rejected_and_reported_as_warning(
    monkeypatch, tmp_path: Path
) -> None:
    now = datetime(2026, 7, 11, 1, 10, tzinfo=UTC)
    module = _prepare(
        monkeypatch,
        tmp_path,
        snapshot_ts=now - timedelta(minutes=10),
        now=now,
    )
    _update_fills(
        tmp_path,
        "UPDATE fills SET fee_usdt = ? WHERE fill_id = ?",
        [float("inf"), "fee-clean"],
    )

    pnl = module.collect_pnl()

    assert pnl["ok"] is True
    assert pnl["commission"] == 0.0
    assert any("fee_usdt sonlu sayı değil" in warning for warning in pnl["warnings"])
    _assert_all_floats_finite(pnl)


def test_api_stale_zero_position_log_is_degraded_not_authoritative_zero(
    monkeypatch, tmp_path: Path
) -> None:
    now = datetime(2026, 7, 11, 1, 10, tzinfo=UTC)
    module = _prepare(
        monkeypatch,
        tmp_path,
        snapshot_ts=now - timedelta(minutes=10),
        now=now,
    )
    _update_journal(
        tmp_path,
        "UPDATE futures_equity_snapshots SET n_positions = 0, unrealized_pnl = 0",
        [],
    )
    _replace_pos_check(
        tmp_path,
        now=now,
        line="[01:00:00Z] POS_CHECK: 0 pozisyon, 0 algo orders [API_STALE]",
    )

    pnl = module.collect_pnl()

    assert pnl["ok"] is True
    assert pnl["positions_ok"] is False
    assert pnl["n_pos"] is None
    assert pnl["n_pos_green"] is None
    assert any("API_STALE" in warning for warning in pnl["warnings"])


def test_healthy_turkish_zero_position_log_remains_authoritative_zero(
    monkeypatch, tmp_path: Path
) -> None:
    now = datetime(2026, 7, 11, 1, 10, tzinfo=UTC)
    module = _prepare(
        monkeypatch,
        tmp_path,
        snapshot_ts=now - timedelta(minutes=10),
        now=now,
    )
    _update_journal(
        tmp_path,
        "UPDATE futures_equity_snapshots SET n_positions = 0, unrealized_pnl = 0",
        [],
    )
    _replace_pos_check(
        tmp_path,
        now=now,
        line="[01:00:00Z] POS_CHECK: 0 pozisyon, 0 algo orders",
    )

    pnl = module.collect_pnl()

    assert pnl["positions_ok"] is True
    assert pnl["n_pos"] == 0
    assert pnl["positions"] == []


def test_negative_position_count_is_degraded(monkeypatch, tmp_path: Path) -> None:
    now = datetime(2026, 7, 11, 1, 10, tzinfo=UTC)
    module = _prepare(
        monkeypatch,
        tmp_path,
        snapshot_ts=now - timedelta(minutes=10),
        now=now,
    )
    _replace_pos_check(
        tmp_path,
        now=now,
        line="[01:00:00Z] POS_CHECK: -1 pos, 0 algo orders",
    )

    pnl = module.collect_pnl()

    assert pnl["positions_ok"] is False
    assert pnl["n_pos"] is None
    assert any("geçersiz sayaç" in warning for warning in pnl["warnings"])


def test_dashboard_renders_warnings_and_does_not_invent_fee_adjusted_net() -> None:
    html = (ROOT / "scripts" / "dashboard" / "index.html").read_text(encoding="utf-8")

    assert "function pnlNotices(p)" in html
    assert "p.warnings" in html
    assert "Journal PnL’ye eklenmez" in html
    assert "POS_CHECK kanıtında yok" in html
    assert "pozisyon kanıtı güvenilir değil — sıfır pozisyon varsayılmadı" in html
    assert "Realized (fee hariç)" not in html
    assert "realizedGross+fee" not in html
    assert "net (fee sonrası)" not in html
