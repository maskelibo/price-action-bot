"""SlippageTracker TF-bucket testleri — SEC31.

Yeni ozellikler:
  - record_fill(..., tf="15m") → TF bucket
  - daily_summary(tf="15m") → TF-spesifik threshold'lar
  - tf_histogram("15m") → histogram/budget raporu

Senaryolar:
  1) test_record_fill_tf_stored         — tf kolonu fills tablosuna yaziliyor
  2) test_daily_summary_tf_filter       — tf filtresi dogru calistiyor
  3) test_tf_budget_thresholds_15m      — 15m: warning=15bps, critical=30bps
  4) test_tf_budget_thresholds_1m       — 1m: warning=10bps, critical=20bps
  5) test_tf_histogram_empty            — bos histogram (no fills)
  6) test_tf_histogram_with_fills       — histogram pct_over_warning dogrulama
  7) test_single_fill_alarm_tf_scaled   — 1m single_max=15bps (15m=22bps)
"""
from __future__ import annotations

import tempfile
from datetime import datetime, timezone
from pathlib import Path

import pytest

from price_action.execution.slippage_tracker import SlippageTracker, TF_SLIPPAGE_BUDGET


def _tracker(tmp_path: Path) -> SlippageTracker:
    db = tmp_path / "test_fills.duckdb"
    return SlippageTracker(db_path=db)


def _fill(tracker: SlippageTracker, fill_id: str, slippage_bps_target: float,
          tf: str = "1d", side: str = "long") -> float:
    """Belirli slippage olusturacak sekilde fill kaydet."""
    expected = 1000.0
    if side == "long":
        realized = expected + slippage_bps_target / 10_000 * expected
    else:
        realized = expected - slippage_bps_target / 10_000 * expected

    ts = datetime.now(timezone.utc)
    return tracker.record_fill(
        fill_id=fill_id,
        ts=ts,
        symbol="BTC/USDT",
        strategy="test",
        side=side,
        expected_price=expected,
        realized_price=realized,
        quantity=0.01,
        fee_usdt=0.08,
        is_maker=True,
        order_type="limit",
        mode="paper",
        tf=tf,
    )


# ===== Testler =====

def test_record_fill_tf_stored(tmp_path):
    """Senaryo 1: tf degeri fills tablosuna yaziliyor."""
    import duckdb
    t = _tracker(tmp_path)
    _fill(t, "f1", slippage_bps_target=5.0, tf="15m")

    con = duckdb.connect(str(tmp_path / "test_fills.duckdb"))
    tf_val = con.execute("SELECT tf FROM fills WHERE fill_id = 'f1'").fetchone()[0]
    con.close()
    assert tf_val == "15m"


def test_record_fill_default_tf_is_1d(tmp_path):
    """Default tf '1d' olarak kaydedilmeli."""
    import duckdb
    t = _tracker(tmp_path)
    # tf vermeden cagir
    ts = datetime.now(timezone.utc)
    t.record_fill(
        fill_id="f_default",
        ts=ts,
        symbol="ETH/USDT",
        strategy="test",
        side="long",
        expected_price=2000.0,
        realized_price=2002.0,
        quantity=0.1,
        fee_usdt=0.16,
        is_maker=False,
        order_type="market",
        mode="paper",
    )
    con = duckdb.connect(str(tmp_path / "test_fills.duckdb"))
    tf_val = con.execute("SELECT tf FROM fills WHERE fill_id = 'f_default'").fetchone()[0]
    con.close()
    assert tf_val == "1d"


def test_daily_summary_tf_filter(tmp_path):
    """Senaryo 2: tf filtresi ile sadece ilgili tf fill'leri sayiliyor."""
    t = _tracker(tmp_path)
    _fill(t, "a1", slippage_bps_target=5.0, tf="15m")
    _fill(t, "a2", slippage_bps_target=5.0, tf="15m")
    _fill(t, "a3", slippage_bps_target=8.0, tf="1m")

    summary_15m = t.daily_summary(tf="15m")
    summary_1m  = t.daily_summary(tf="1m")

    assert summary_15m["n_fills"] == 2
    assert summary_1m["n_fills"] == 1
    assert summary_15m["tf"] == "15m"
    assert summary_1m["tf"] == "1m"


def test_tf_budget_thresholds_15m(tmp_path):
    """Senaryo 3: 15m budget — warning=15bps, critical=30bps."""
    budget = TF_SLIPPAGE_BUDGET["15m"]
    assert budget["warning"] == pytest.approx(15.0)
    assert budget["critical"] == pytest.approx(30.0)
    assert budget["single_max"] == pytest.approx(22.0)


def test_tf_budget_thresholds_1m(tmp_path):
    """Senaryo 4: 1m budget — warning=10bps, critical=20bps."""
    budget = TF_SLIPPAGE_BUDGET["1m"]
    assert budget["warning"] == pytest.approx(10.0)
    assert budget["critical"] == pytest.approx(20.0)
    assert budget["single_max"] == pytest.approx(15.0)


def test_tf_budget_thresholds_5m():
    """5m budget — warning=12bps, critical=24bps."""
    budget = TF_SLIPPAGE_BUDGET["5m"]
    assert budget["warning"] == pytest.approx(12.0)
    assert budget["critical"] == pytest.approx(24.0)


def test_tf_histogram_empty(tmp_path):
    """Senaryo 5: bos histogram (fill yok)."""
    t = _tracker(tmp_path)
    hist = t.tf_histogram("1m")

    assert hist["tf"] == "1m"
    assert hist["n_fills"] == 0
    assert hist["mean_bps"] == pytest.approx(0.0)
    assert hist["budget_warning_bps"] == pytest.approx(10.0)
    assert hist["budget_critical_bps"] == pytest.approx(20.0)


def test_tf_histogram_with_fills(tmp_path):
    """Senaryo 6: histogram pct_over_warning dogrulama."""
    t = _tracker(tmp_path)
    # 3 fill: 5bps, 12bps, 25bps (15m budget warning=15, critical=30)
    _fill(t, "h1", 5.0, tf="15m")
    _fill(t, "h2", 12.0, tf="15m")
    _fill(t, "h3", 25.0, tf="15m")

    hist = t.tf_histogram("15m")

    assert hist["n_fills"] == 3
    assert hist["mean_bps"] == pytest.approx((5 + 12 + 25) / 3, abs=0.5)
    # 1/3 over warning (15bps): 25bps
    assert hist["pct_over_warning"] == pytest.approx(33.3, abs=1.0)
    # 0/3 over critical (30bps)
    assert hist["pct_over_critical"] == pytest.approx(0.0, abs=0.1)
    assert hist["budget_warning_bps"] == pytest.approx(15.0)


def test_alarm_fires_on_tf_critical(tmp_path, capsys):
    """daily_summary TF-threshold ile alarm tetikleniyor mu?"""
    t = _tracker(tmp_path)
    # 1m critical = 20bps, 25bps fill ekle
    _fill(t, "alarm1", 25.0, tf="1m")

    summary = t.daily_summary(tf="1m")
    # 25bps > 20bps → CRITICAL
    assert summary["alarm_level"] == "CRITICAL"
    assert summary["alarm_triggered"] is True
