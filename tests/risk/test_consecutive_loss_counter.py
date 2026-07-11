"""SEC26.B-3: Consecutive-loss counter + DDBreaker cool-down semantik testleri.

Backtest engine `lab.py` 3 ardışık kayıp -> 5 gün halt + counter reset uyguluyor;
live `count_consecutive_losses()` daha önce hardcoded 0 dönüyordu. Bu testler:

  1. Boş tablo -> 0 (no_trades_returns_zero)
  2. 1 loss -> 1 (one_loss_returns_one)
  3. 3 ardışık loss -> 3 (three_losses_returns_three)
  4. L,L,W,L,L -> 2 (win_breaks_streak)
  5. 30g öncesi loss sayılmaz (only_last_30_days_counted)
  6. Counter 3 -> breaker halt + 5g cool-down timer (threshold_3_triggers_halt)
  7. Counter 2 -> halt yok (below_threshold_does_not_halt)
  8. Cool-down 5g sonra auto-clear (cool_down_expires_after_pause_days)
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import duckdb
import pytest

from price_action.risk.breaker import DDBreaker
from price_action.risk.sizing import AccountState
from scripts.lib.risk_integration import count_consecutive_losses

# =====================================================================
# Helpers — futures_trades_closed tablosunu oluştur + satır ekle
# =====================================================================


def _create_schema(db_path: Path) -> None:
    con = duckdb.connect(str(db_path))
    con.execute("""
        CREATE TABLE IF NOT EXISTS futures_trades_closed (
            trade_id TEXT PRIMARY KEY,
            ts_open TIMESTAMP,
            ts_close TIMESTAMP,
            sym TEXT,
            side TEXT,
            strategy TEXT,
            entry_price DOUBLE,
            exit_price DOUBLE,
            qty DOUBLE,
            realized_pnl_usdt DOUBLE,
            realized_r DOUBLE,
            win BOOLEAN,
            close_reason TEXT
        )
    """)
    con.commit()
    con.close()


def _insert_trade(
    db_path: Path,
    *,
    trade_id: str,
    ts_close: datetime,
    win: bool,
    sym: str = "BTC/USDT",
    side: str = "long",
) -> None:
    con = duckdb.connect(str(db_path))
    con.execute(
        """
        INSERT INTO futures_trades_closed
            (trade_id, ts_open, ts_close, sym, side, strategy,
             entry_price, exit_price, qty, realized_pnl_usdt, realized_r,
             win, close_reason)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            trade_id,
            ts_close - timedelta(hours=4),
            ts_close,
            sym,
            side,
            "test_strat",
            100.0,
            110.0 if win else 90.0,
            1.0,
            10.0 if win else -10.0,
            1.0 if win else -1.0,
            win,
            "tp" if win else "sl",
        ],
    )
    con.commit()
    con.close()


@pytest.fixture
def journal_path(tmp_path: Path) -> Path:
    """Boş futures_journal.duckdb (sadece schema)."""
    p = tmp_path / "futures_journal.duckdb"
    _create_schema(p)
    return p


@pytest.fixture
def breaker_config() -> dict:
    """SEC26.B-3 lab.py parity preset (configs/risk_balanced.yaml)."""
    return {
        "daily_loss_pct": 0.99,  # disabled
        "weekly_loss_pct": 0.99,
        "monthly_loss_pct": 0.99,
        "consecutive_losses": 3,  # lab.py production threshold
        "consecutive_loss_pause_days": 5,  # lab.py production halt
    }


T0 = datetime(2026, 5, 15, 12, 0, tzinfo=UTC)


def _acct(equity: float, consec: int = 0) -> AccountState:
    return AccountState(
        equity_usdt=equity,
        free_margin_usdt=equity,
        consecutive_losses=consec,
    )


# =====================================================================
# 1. count_consecutive_losses() — pool query tests
# =====================================================================


def test_no_trades_returns_zero(journal_path):
    """Boş journal -> 0 (graceful fallback)."""
    assert count_consecutive_losses(journal_path) == 0


def test_missing_journal_returns_zero(tmp_path):
    """Tablo veya dosya yok -> 0 (eski daemon kurulumları backward-compat)."""
    missing = tmp_path / "nonexistent.duckdb"
    assert count_consecutive_losses(missing) == 0


def test_one_loss_returns_one(journal_path):
    """Tek loss -> 1."""
    _insert_trade(
        journal_path, trade_id="T1", ts_close=datetime.now(UTC) - timedelta(hours=1), win=False
    )
    assert count_consecutive_losses(journal_path) == 1


def test_three_losses_returns_three(journal_path):
    """3 ardışık loss -> 3."""
    now = datetime.now(UTC)
    _insert_trade(journal_path, trade_id="T1", ts_close=now - timedelta(hours=6), win=False)
    _insert_trade(journal_path, trade_id="T2", ts_close=now - timedelta(hours=4), win=False)
    _insert_trade(journal_path, trade_id="T3", ts_close=now - timedelta(hours=2), win=False)
    assert count_consecutive_losses(journal_path) == 3


def test_default_counter_does_not_saturate_at_legacy_twenty_row_limit(journal_path):
    now = datetime.now(UTC)
    for index in range(25):
        _insert_trade(
            journal_path,
            trade_id=f"T{index:02d}",
            ts_close=now - timedelta(minutes=25 - index),
            win=False,
        )

    assert count_consecutive_losses(journal_path) == 25
    assert count_consecutive_losses(journal_path, n_max=20) == 20


def test_win_breaks_streak(journal_path):
    """L, L, W, L, L (en yenisi en sondaki L) -> 2 (en yeni 2 loss sonra win)."""
    now = datetime.now(UTC)
    # En eskiden en yeniye: L, L, W, L, L
    _insert_trade(journal_path, trade_id="T1", ts_close=now - timedelta(hours=10), win=False)
    _insert_trade(journal_path, trade_id="T2", ts_close=now - timedelta(hours=8), win=False)
    _insert_trade(
        journal_path, trade_id="T3", ts_close=now - timedelta(hours=6), win=True
    )  # streak resetler
    _insert_trade(journal_path, trade_id="T4", ts_close=now - timedelta(hours=4), win=False)
    _insert_trade(journal_path, trade_id="T5", ts_close=now - timedelta(hours=2), win=False)
    # Geriye doğru: T5(L), T4(L), T3(W) -> dur -> counter=2
    assert count_consecutive_losses(journal_path) == 2


def test_exact_zero_final_pnl_breaks_loss_streak(journal_path):
    """Exact breakeven final row is neutral, not a consecutive loss."""
    now = datetime.now(UTC)
    _insert_trade(journal_path, trade_id="T1", ts_close=now - timedelta(hours=6), win=False)
    _insert_trade(journal_path, trade_id="T0", ts_close=now - timedelta(hours=4), win=False)
    con = duckdb.connect(str(journal_path))
    con.execute("UPDATE futures_trades_closed SET realized_pnl_usdt = 0.0 WHERE trade_id = 'T0'")
    con.close()
    _insert_trade(journal_path, trade_id="T2", ts_close=now - timedelta(hours=2), win=False)

    assert count_consecutive_losses(journal_path) == 1


def test_realized_pnl_sign_is_authoritative_not_win_flag(journal_path):
    """Yalnız PnL < 0 loss'tur; bayat/yanlış win boolean'i kararı değiştirmez."""
    now = datetime.now(UTC)
    _insert_trade(journal_path, trade_id="OLDER", ts_close=now - timedelta(hours=3), win=False)
    _insert_trade(journal_path, trade_id="NEWEST", ts_close=now - timedelta(hours=1), win=True)
    con = duckdb.connect(str(journal_path))
    con.execute(
        "UPDATE futures_trades_closed SET realized_pnl_usdt = -1.0, win = TRUE "
        "WHERE trade_id = 'NEWEST'"
    )
    con.execute(
        "UPDATE futures_trades_closed SET realized_pnl_usdt = 1.0, win = FALSE "
        "WHERE trade_id = 'OLDER'"
    )
    con.close()

    assert count_consecutive_losses(journal_path) == 1


def test_only_last_30_days_counted(journal_path):
    """30+ gün önceki loss sayılmaz (default lookback)."""
    now = datetime.now(UTC)
    # 45 gün önce 3 loss (kapsam dışı), bugün 1 loss
    _insert_trade(journal_path, trade_id="T1", ts_close=now - timedelta(days=45), win=False)
    _insert_trade(journal_path, trade_id="T2", ts_close=now - timedelta(days=44), win=False)
    _insert_trade(journal_path, trade_id="T3", ts_close=now - timedelta(days=43), win=False)
    _insert_trade(journal_path, trade_id="T4", ts_close=now - timedelta(hours=1), win=False)
    # Sadece T4 lookback içinde -> counter=1
    assert count_consecutive_losses(journal_path, lookback_days=30) == 1


def test_intermixed_old_and_recent(journal_path):
    """Eski win lookback dışında -> sayım dahili kalır (sınır testi)."""
    now = datetime.now(UTC)
    _insert_trade(journal_path, trade_id="T_old_W", ts_close=now - timedelta(days=100), win=True)
    _insert_trade(journal_path, trade_id="T1", ts_close=now - timedelta(days=2), win=False)
    _insert_trade(journal_path, trade_id="T2", ts_close=now - timedelta(days=1), win=False)
    # Lookback içinde 2 loss, win yok -> 2
    assert count_consecutive_losses(journal_path, lookback_days=30) == 2


# =====================================================================
# 2. DDBreaker cool-down semantik tests
# =====================================================================


def test_threshold_3_triggers_halt(tmp_path, breaker_config):
    """Counter 3'e ulaşınca triggered_consecutive=True + cool-down timer set."""
    breaker = DDBreaker(breaker_config, state_path=tmp_path / "br.json")
    snap = breaker.update(_acct(10_000, consec=3), now=T0)
    assert snap["consecutive"] is True
    # Cool-down timer set edildi
    assert breaker.state.blocked_consecutive_until != ""
    # T0 + 5 gün civarı
    from datetime import datetime as _dt

    expiry = _dt.fromisoformat(breaker.state.blocked_consecutive_until)
    expected = T0 + timedelta(days=5)
    assert abs((expiry - expected).total_seconds()) < 5


def test_below_threshold_does_not_halt(tmp_path, breaker_config):
    """Counter 2 -> halt yok, timer set olmaz."""
    breaker = DDBreaker(breaker_config, state_path=tmp_path / "br.json")
    snap = breaker.update(_acct(10_000, consec=2), now=T0)
    assert snap["consecutive"] is False
    assert breaker.state.blocked_consecutive_until == ""


def test_threshold_4_also_triggers(tmp_path, breaker_config):
    """N >= 3 (eşik üstü) -> halt (>=, not ==)."""
    breaker = DDBreaker(breaker_config, state_path=tmp_path / "br.json")
    snap = breaker.update(_acct(10_000, consec=4), now=T0)
    assert snap["consecutive"] is True


def test_cool_down_expires_after_pause_days(tmp_path, breaker_config):
    """DEADLOCK FIX (2026-05-21): cool-down dolunca counter HALEN eşikteyse
    yeniden tetiklenMEZ — consec_consumed watermark eski streak'i tüketmiştir.
    (Eski bug: aynı streak sonsuza dek yeniden tetikliyordu; bot halt'ta
    kazanç alamadığı için kalıcı kilit.)"""
    breaker = DDBreaker(breaker_config, state_path=tmp_path / "br.json")
    # T0: tetikle (counter=3) → consec_consumed=3 olur
    breaker.update(_acct(10_000, consec=3), now=T0)
    assert breaker.state.triggered_consecutive is True
    assert breaker.state.consec_consumed == 3
    # T0 + 5g + 1h: cool-down expired, counter HALEN 3 (yeni kayıp yok).
    # effective = 3 - 3 = 0 < eşik → trigger=False (deadlock kırıldı).
    future = T0 + timedelta(days=5, hours=1)
    snap = breaker.update(_acct(10_000, consec=3), now=future)
    assert snap["consecutive"] is False, "halt servis edildi — yeniden tetiklenmemeli"
    assert breaker.state.blocked_consecutive_until == ""


def test_new_losses_after_cooldown_retrigger(tmp_path, breaker_config):
    """Halt servis edildikten SONRA N YENİ kayıp → yeniden tetiklenir
    (lab.py parity: fresh streak). consec_consumed watermark üstüne sayar."""
    breaker = DDBreaker(breaker_config, state_path=tmp_path / "br.json")
    breaker.update(_acct(10_000, consec=3), now=T0)  # tetik, consumed=3
    future = T0 + timedelta(days=5, hours=1)
    breaker.update(_acct(10_000, consec=3), now=future)  # expired → serbest
    assert breaker.state.triggered_consecutive is False
    # 3 YENİ kayıp (counter 6) → effective = 6 - 3 = 3 >= eşik → re-trigger
    snap = breaker.update(_acct(10_000, consec=6), now=future + timedelta(hours=1))
    assert snap["consecutive"] is True


def test_cool_down_expires_and_counter_dropped(tmp_path, breaker_config):
    """Cool-down dolar + counter <3 -> trigger=False (full recovery)."""
    breaker = DDBreaker(breaker_config, state_path=tmp_path / "br.json")
    breaker.update(_acct(10_000, consec=3), now=T0)
    assert breaker.state.triggered_consecutive is True
    # 5g sonra counter düştü (yeni win'ler journal'a yazıldı, journal counter <3)
    future = T0 + timedelta(days=5, hours=1)
    snap = breaker.update(_acct(10_000, consec=0), now=future)
    assert snap["consecutive"] is False
    assert breaker.state.blocked_consecutive_until == ""


def test_during_cool_down_blocked(tmp_path, breaker_config):
    """Cool-down aktif iken counter düşse bile trigger=True (halt sürer)."""
    breaker = DDBreaker(breaker_config, state_path=tmp_path / "br.json")
    breaker.update(_acct(10_000, consec=3), now=T0)
    # 2 gün sonra (cool-down halen aktif, expiry T0+5g)
    mid = T0 + timedelta(days=2)
    # Counter düşse bile (örn. yeni win journal'a yazıldı) cool-down süresi henüz dolmadı
    snap = breaker.update(_acct(10_000, consec=0), now=mid)
    assert snap["consecutive"] is True  # halt sürer
    assert breaker.state.blocked_consecutive_until != ""


def test_disabled_pause_days_default(tmp_path):
    """consecutive_loss_pause_days YAML'da yoksa default 5 (backward-compat)."""
    cfg = {
        "consecutive_losses": 3,
        # pause_days yok!
    }
    breaker = DDBreaker(cfg, state_path=tmp_path / "br.json")
    breaker.update(_acct(10_000, consec=3), now=T0)
    from datetime import datetime as _dt

    expiry = _dt.fromisoformat(breaker.state.blocked_consecutive_until)
    assert abs((expiry - (T0 + timedelta(days=5))).total_seconds()) < 5


def test_subday_pause_days_15m_scalp(tmp_path):
    """SEC-SCALP-B1: pause_days=0.5 -> 12h cool-down (int() bug regression).

    Önceki int(0.5)=0 -> timedelta(days=0) -> cool-down anında expire.
    float() cast sonrası: 0.5g = 12h gerçek cool-down.
    """
    cfg = {
        "consecutive_losses": 8,
        "consecutive_loss_pause_days": 0.5,  # 5m scalp preset
    }
    breaker = DDBreaker(cfg, state_path=tmp_path / "br.json")
    breaker.update(_acct(10_000, consec=8), now=T0)
    from datetime import datetime as _dt

    expiry = _dt.fromisoformat(breaker.state.blocked_consecutive_until)
    expected = T0 + timedelta(hours=12)
    delta = abs((expiry - expected).total_seconds())
    assert delta < 5, f"Expected ~12h cool-down, got expiry={expiry} (delta={delta}s)"


def test_subday_pause_days_1m_scalp(tmp_path):
    """SEC-SCALP-B1: pause_days=0.25 -> 6h cool-down."""
    cfg = {
        "consecutive_losses": 12,
        "consecutive_loss_pause_days": 0.25,  # 1m scalp preset (archived ama parity)
    }
    breaker = DDBreaker(cfg, state_path=tmp_path / "br.json")
    breaker.update(_acct(10_000, consec=12), now=T0)
    from datetime import datetime as _dt

    expiry = _dt.fromisoformat(breaker.state.blocked_consecutive_until)
    expected = T0 + timedelta(hours=6)
    delta = abs((expiry - expected).total_seconds())
    assert delta < 5, f"Expected ~6h cool-down, got expiry={expiry} (delta={delta}s)"


def test_backward_compat_no_pause_days_no_change(tmp_path):
    """Eski state JSON'da blocked_consecutive_until yoksa -> default "" (no crash)."""
    state_path = tmp_path / "br.json"
    # Eski state dosyası simüle et (B-1 öncesi)
    import json

    state_path.write_text(
        json.dumps(
            {
                "daily_pnl": 0.0,
                "weekly_pnl": 0.0,
                "monthly_pnl": 0.0,
                "consecutive_losses": 0,
                "daily_anchor_equity": 10_000.0,
                "weekly_anchor_equity": 10_000.0,
                "monthly_anchor_equity": 10_000.0,
                "last_reset_daily": "",
                "last_reset_weekly": "",
                "last_reset_monthly": "",
                "triggered_daily": False,
                "triggered_weekly": False,
                "triggered_monthly": False,
                "triggered_consecutive": False,
                # NOT: blocked_consecutive_until YOK (eski state)
            }
        )
    )
    breaker = DDBreaker({"consecutive_losses": 3}, state_path=state_path)
    # Yeni alan default "" olarak ulaşır
    assert breaker.state.blocked_consecutive_until == ""
    # Update normal çalışır
    snap = breaker.update(_acct(10_000, consec=0), now=T0)
    assert snap["consecutive"] is False
