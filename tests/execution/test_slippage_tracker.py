"""Slippage Tracker testleri.

- Fill kayıt + hesaplama doğruluğu
- Günlük aggregat
- Alarm eşikleri
- JSONL log çıktısı
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest

from price_action.execution.slippage_tracker import SlippageTracker, ALARM_WARNING_BPS


@pytest.fixture
def tracker(tmp_path):
    db = tmp_path / "slip_test.duckdb"
    t = SlippageTracker(db_path=db)
    # JSONL log'u tmp'ye yönlendir (monkeypatch değil, instance attr)
    t._log_dir_override = tmp_path  # opsiyonel — tracker kendi LOG_DIR'ini kullanır
    return t


def _fill(tracker, symbol="BTC/USDT", side="long",
          expected=65000.0, realized=65065.0, qty=0.01, fee=0.048):
    return tracker.record_fill(
        fill_id=uuid.uuid4().hex[:20],
        ts=datetime.now(timezone.utc),
        symbol=symbol,
        strategy="engulfing_continuation",
        side=side,
        expected_price=expected,
        realized_price=realized,
        quantity=qty,
        fee_usdt=fee,
        is_maker=False,
        order_type="market",
        mode="paper",
    )


def test_slippage_long_positive(tracker):
    """LONG: realized > expected → pozitif slippage (maliyet)."""
    slip = _fill(tracker, side="long", expected=65000.0, realized=65065.0)
    assert slip == pytest.approx(10.0, rel=0.01)  # 10 bps


def test_slippage_short_positive(tracker):
    """SHORT: realized < expected → pozitif slippage (maliyet)."""
    slip = _fill(tracker, side="short", expected=65000.0, realized=64935.0)
    assert slip == pytest.approx(10.0, rel=0.01)


def test_slippage_maker_zero(tracker):
    """Post-only maker: realized = expected → 0 slippage."""
    slip = _fill(tracker, expected=65000.0, realized=65000.0)
    assert slip == pytest.approx(0.0, abs=0.01)


def test_daily_summary_aggregates(tracker):
    # 5 fill, çeşitli slippage
    for _ in range(5):
        _fill(tracker, expected=65000.0, realized=65065.0)  # 10 bps her biri

    summary = tracker.daily_summary()
    assert summary["n_fills"] == 5
    assert summary["avg_slippage_bps"] == pytest.approx(10.0, rel=0.05)
    assert summary["max_slippage_bps"] == pytest.approx(10.0, rel=0.05)


def test_alarm_warning_triggered(tracker):
    """avg slippage > ALARM_WARNING_BPS → alarm."""
    # Fill'ler yüksek slippage
    high_slip_realized = 65000.0 * (1 + (ALARM_WARNING_BPS + 5) / 10_000)
    for _ in range(3):
        _fill(tracker, expected=65000.0, realized=high_slip_realized)

    summary = tracker.daily_summary()
    assert summary["alarm_triggered"] is True
    assert summary["alarm_level"] in ("WARNING", "CRITICAL")


def test_alarm_not_triggered_low_slippage(tracker):
    """avg slippage < 5 bps → alarm yok."""
    low_slip_realized = 65000.0 * (1 + 3 / 10_000)  # 3 bps
    for _ in range(5):
        _fill(tracker, expected=65000.0, realized=low_slip_realized)

    summary = tracker.daily_summary()
    assert not summary["alarm_triggered"]
    assert summary["alarm_level"] == "OK"


def test_get_recent_fills(tracker):
    for _ in range(3):
        _fill(tracker)
    fills = tracker.get_recent_fills(days=1)
    assert len(fills) >= 3
    assert all("slippage_bps" in f for f in fills)


def test_fill_idempotent_insert(tracker):
    """Aynı fill_id iki kez → ikinci INSERT OR IGNORE, kayıt 1."""
    fid = "test_fill_001"
    tracker.record_fill(
        fill_id=fid, ts=datetime.now(timezone.utc),
        symbol="ETH/USDT", strategy="test", side="long",
        expected_price=3000.0, realized_price=3003.0, quantity=0.5,
        fee_usdt=0.01, is_maker=False, order_type="market", mode="paper",
    )
    tracker.record_fill(
        fill_id=fid, ts=datetime.now(timezone.utc),
        symbol="ETH/USDT", strategy="test", side="long",
        expected_price=3000.0, realized_price=3003.0, quantity=0.5,
        fee_usdt=0.01, is_maker=False, order_type="market", mode="paper",
    )
    fills = tracker.get_recent_fills(days=1)
    matching = [f for f in fills if f["symbol"] == "ETH/USDT"]
    assert len(matching) == 1  # duplicate yok
