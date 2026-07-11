"""F3 aylık breaker journal-feed — kapanış sprinti 2026-07-10 (DERIN_DENETIM F3 CRIT).

Aylık side breaker (monthly_pnl_long/short → triggered_monthly_* → check_side
Reject) tanımlıydı ama beslemesi ÖLÜYDÜ: record_realized_pnl'i hiçbir canlı yol
çağırmıyordu → canlıda aylık zarar freni fiilen YOKTU. Fix: daily_pnl'in
SEC26.B-4 deseni — journal-SUM feed'i AccountState üzerinden her tick
(restart-proof, idempotent; event-akümülasyonun restart-replay çift-sayım
riski yok). None-sentinel: feed yoksa eski event-akümülasyon davranışı korunur.
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from price_action.execution.trade_journal import TradeJournal  # noqa: E402
from price_action.risk.breaker import DDBreaker  # noqa: E402
from price_action.risk.sizing import AccountState  # noqa: E402


def _seed_journal(tmp_path, closes, partials=()):
    """closes/partials: (side, pnl, ts_close aware-UTC) üçlüleri."""
    db = tmp_path / "j.duckdb"
    tj = TradeJournal(db_path=str(db))
    for i, (side, pnl, ts) in enumerate(closes):
        tj.record_close(
            trade_id=f"t{i}",
            ts_open=ts,
            ts_close=ts,
            sym="X/USDT",
            side=side,
            strategy="s",
            entry_price=100.0,
            exit_price=100.0,
            qty=1.0,
            sl_price=95.0,
            close_reason="sl",
            realized_pnl_override=pnl,
        )
    for i, (side, pnl, ts) in enumerate(partials):
        tj.record_partial_close(
            close_id=f"p{i}",
            trade_id=f"pt{i}",
            ts_close=ts,
            sym="X/USDT",
            side=side,
            strategy="s",
            entry_price=100.0,
            exit_price=100.0,
            qty_closed=0.3,
            sl_price=95.0,
            close_reason="tp1",
        )
        # partial PnL'i hesaplanır (entry==exit → 0); override yok — test için
        # doğrudan tabloya yaz
        import duckdb

        con = duckdb.connect(str(db))
        con.execute(
            "UPDATE futures_partial_closes SET realized_pnl_usdt=? WHERE close_id=?",
            [pnl, f"p{i}"],
        )
        con.commit()
        con.close()
    return db


NOW = datetime(2026, 7, 10, 12, 0, tzinfo=UTC)
THIS_MONTH = datetime(2026, 7, 5, 10, 0, tzinfo=UTC)
LAST_MONTH = datetime(2026, 6, 25, 10, 0, tzinfo=UTC)


# ── Journal katmanı ──────────────────────────────────────────────────────────


def test_month_by_side_sums_closed_and_partials(tmp_path):
    db = _seed_journal(
        tmp_path,
        closes=[
            ("long", -100.0, THIS_MONTH),
            ("long", -50.0, THIS_MONTH),
            ("short", 30.0, THIS_MONTH),
        ],
        partials=[("long", -20.0, THIS_MONTH)],
    )
    long_pnl, short_pnl = TradeJournal(db_path=str(db)).get_realized_pnl_month_by_side(now=NOW)
    assert abs(long_pnl - (-170.0)) < 1e-6
    assert abs(short_pnl - 30.0) < 1e-6


def test_month_window_excludes_prior_month(tmp_path):
    db = _seed_journal(
        tmp_path,
        closes=[("long", -500.0, LAST_MONTH), ("long", -10.0, THIS_MONTH)],
    )
    long_pnl, _ = TradeJournal(db_path=str(db)).get_realized_pnl_month_by_side(now=NOW)
    assert abs(long_pnl - (-10.0)) < 1e-6  # geçen ayın -500'ü GİRMEZ


def test_fresh_db_returns_zeroes(tmp_path):
    db = tmp_path / "fresh.duckdb"
    TradeJournal(db_path=str(db))  # şema kur
    assert TradeJournal(db_path=str(db)).get_realized_pnl_month_by_side(now=NOW) == (0.0, 0.0)


# ── risk_integration katmanı ─────────────────────────────────────────────────


def test_wrapper_missing_journal_returns_zeroes():
    from scripts.lib.risk_integration import realized_pnl_month_by_side_futures

    assert realized_pnl_month_by_side_futures("/yok/boyle/bir.duckdb") == (0.0, 0.0)


def test_wrapper_reads_seeded_journal(tmp_path):
    from scripts.lib.risk_integration import realized_pnl_month_by_side_futures

    db = _seed_journal(tmp_path, closes=[("short", -42.0, THIS_MONTH)])
    ml, ms = realized_pnl_month_by_side_futures(db)
    assert ml == 0.0
    assert ms is not None and abs(ms - (-42.0)) < 1e-6


def test_daily_wrapper_uses_partial_only_journal_without_wallet_fallback(tmp_path):
    from scripts.lib.risk_integration import realized_pnl_today_futures

    now = NOW
    db = _seed_journal(tmp_path, closes=[], partials=[("long", -17.5, now)])
    con = duckdb.connect(str(db))
    con.execute(
        """
        CREATE TABLE futures_equity_snapshots (
            ts TIMESTAMP,
            wallet_balance DOUBLE
        )
        """
    )
    con.execute(
        "INSERT INTO futures_equity_snapshots VALUES (?, ?), (?, ?)",
        [now.replace(hour=0, minute=1), 10000.0, now, 12000.0],
    )
    con.close()

    # Journal partial is authoritative; the +$2,000 wallet delta must not leak
    # into the realized-only daily breaker feed.
    assert realized_pnl_today_futures(db, now=now) == -17.5


def test_daily_wrapper_uses_utc_wallet_delta_only_when_journal_day_is_empty(tmp_path):
    from scripts.lib.risk_integration import realized_pnl_today_futures

    now = NOW
    db = _seed_journal(tmp_path, closes=[])
    con = duckdb.connect(str(db))
    con.execute("CREATE TABLE futures_equity_snapshots (ts TIMESTAMP, wallet_balance DOUBLE)")
    con.execute(
        "INSERT INTO futures_equity_snapshots VALUES (?, ?), (?, ?)",
        [now.replace(hour=0, minute=1), 10000.0, now, 10025.0],
    )
    con.close()

    assert realized_pnl_today_futures(db, now=now) == 25.0


# ── Breaker katmanı (uçtan uca eşik) ─────────────────────────────────────────


def _breaker(tmp_path) -> DDBreaker:
    cfg = {
        "daily_loss_pct": 0.04,
        "weekly_loss_pct": 0.08,
        "monthly_loss_pct": 0.99,
        "monthly_loss_pct_long": 0.12,
        "monthly_loss_pct_short": 0.04,
        "monthly_halt_days": 3,
    }
    return DDBreaker(config=cfg, state_path=tmp_path / "breaker_state.json")


def _acct(equity, ml=None, ms=None) -> AccountState:
    return AccountState(
        equity_usdt=equity,
        free_margin_usdt=equity,
        realized_pnl_month_long=ml,
        realized_pnl_month_short=ms,
    )


def test_journal_feed_triggers_long_halt(tmp_path):
    br = _breaker(tmp_path)
    br.update(_acct(5000.0))  # anchor kur
    br.update(_acct(5000.0, ml=-650.0, ms=0.0))  # long %12 eşiği ($600) aşıldı
    assert br.state.triggered_monthly_long is True
    assert br.state.blocked_long_until != ""
    assert br.check_side("long") is False
    assert br.check_side("short") is True  # long halt short'u etkilemez


def test_journal_feed_triggers_short_halt_at_4pct(tmp_path):
    br = _breaker(tmp_path)
    br.update(_acct(5000.0))
    br.update(_acct(5000.0, ml=0.0, ms=-210.0))  # short %4 eşiği ($200) aşıldı
    assert br.state.triggered_monthly_short is True
    assert br.check_side("short") is False
    assert br.check_side("long") is True


def test_none_feed_preserves_event_accumulation(tmp_path):
    """None-sentinel: feed yoksa eski event-akümülasyon davranışı bozulmaz."""
    br = _breaker(tmp_path)
    br.update(_acct(5000.0))
    br.record_realized_pnl(_acct(5000.0), side="long", pnl_realized=-100.0)
    assert abs(br.state.monthly_pnl_long - (-100.0)) < 1e-6
    # None feed'li update event toplamını EZMEZ
    br.update(_acct(5000.0, ml=None, ms=None))
    assert abs(br.state.monthly_pnl_long - (-100.0)) < 1e-6


def test_journal_feed_overrides_event_accumulation(tmp_path):
    """Journal otoritatif: not-None feed event toplamını EZER (çift sayım imkânsız)."""
    br = _breaker(tmp_path)
    br.update(_acct(5000.0))
    br.record_realized_pnl(_acct(5000.0), side="long", pnl_realized=-100.0)
    br.update(_acct(5000.0, ml=-30.0, ms=0.0))  # journal gerçeği: -30
    assert abs(br.state.monthly_pnl_long - (-30.0)) < 1e-6


def test_safe_deploy_no_trigger_at_current_values(tmp_path):
    """Deploy güvenliği: bugünkü canlı değerlerle (long -10 / short +2,
    anchor ~4963) hiçbir fren tetiklenmemeli."""
    br = _breaker(tmp_path)
    br.update(_acct(4962.78))
    br.update(_acct(4962.78, ml=-10.20, ms=2.04))
    assert br.state.triggered_monthly_long is False
    assert br.state.triggered_monthly_short is False
    assert br.check_side("long") is True
    assert br.check_side("short") is True
