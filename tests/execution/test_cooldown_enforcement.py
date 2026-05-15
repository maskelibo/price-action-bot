"""Cooldown Enforcement Testleri — SEC26.A

Lab.py semantik paritesi: key = (symbol, side), strategy farkı yok.

5 test senaryosu:
  1. test_same_sym_side_within_cooldown_rejected
  2. test_same_sym_side_after_cooldown_accepted
  3. test_different_sym_same_side_accepted
  4. test_different_side_same_sym_accepted
  5. test_cooldown_disabled_in_yaml_no_filter
"""
from __future__ import annotations

import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import duckdb
import pytest

from scripts.lib.cooldown import (
    filter_signals_by_cooldown,
    is_in_cooldown,
    _build_last_entry,
    _query_recent_fills,
)

COOLDOWN_DAYS = 3


# ── yardımcı: geçici journal oluştur ──────────────────────────────────────────

def _make_journal(fills: list[dict]) -> Path:
    """Geçici DuckDB journal oluştur; fills listesindeki 'filled' kayıtları ekle."""
    tmp = tempfile.mktemp(suffix=".duckdb")
    con = duckdb.connect(tmp)
    con.execute("""
        CREATE TABLE futures_signals (
            signal_id VARCHAR PRIMARY KEY,
            ts TIMESTAMP,
            symbol VARCHAR,
            strategy VARCHAR,
            side VARCHAR,
            sl_price DOUBLE,
            tp_price DOUBLE,
            confluence DOUBLE,
            leverage INTEGER,
            status VARCHAR,
            order_id VARCHAR,
            fill_price DOUBLE,
            fill_qty DOUBLE,
            notional_usdt DOUBLE,
            margin_usdt DOUBLE,
            notes VARCHAR
        )
    """)
    for i, f in enumerate(fills):
        con.execute(
            "INSERT INTO futures_signals VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                f"fill_{i}", f["ts"], f["symbol"], f.get("strategy", "test_strat"),
                f["side"], 100.0, 110.0, 0.5, 3, "filled",
                None, 105.0, 1.0, 1000.0, 333.0, None,
            ),
        )
    con.commit()
    con.close()
    return Path(tmp)


def _sig(sym: str, side: str, strategy: str = "engulfing_continuation",
         offset_days: int = 0) -> dict:
    """Bugün (+ offset_days) tarihli test sinyali."""
    ts = datetime.now(timezone.utc) + timedelta(days=offset_days)
    return {"symbol": sym, "side": side, "strategy": strategy, "ts": ts}


# ── Test 1 ─────────────────────────────────────────────────────────────────────

def test_same_sym_side_within_cooldown_rejected():
    """Aynı (symbol, side) cooldown_days içinde fill var → sinyal reddedilmeli.

    Senaryo: 1 gün önce BTC/USDT long fill. Cooldown=3 gün.
    Bugün BTC/USDT long sinyali → reject.
    """
    fill_ts = datetime.now(timezone.utc) - timedelta(days=1)
    journal = _make_journal([{"symbol": "BTC/USDT", "side": "long", "ts": fill_ts}])

    signals = [_sig("BTC/USDT", "long")]
    result = filter_signals_by_cooldown(signals, COOLDOWN_DAYS, journal, "futures_signals")

    assert len(result) == 0, (
        f"Cooldown icindeki sinyal reddedilmeli, ama {len(result)} kaldi"
    )


# ── Test 2 ─────────────────────────────────────────────────────────────────────

def test_same_sym_side_after_cooldown_accepted():
    """Aynı (symbol, side) ama cooldown_days'ten SONRA → sinyal kabul edilmeli.

    Senaryo: 5 gün önce BTC/USDT long fill. Cooldown=3 gün.
    Bugün BTC/USDT long sinyali → ACCEPT (5 >= 3).
    """
    fill_ts = datetime.now(timezone.utc) - timedelta(days=5)
    journal = _make_journal([{"symbol": "BTC/USDT", "side": "long", "ts": fill_ts}])

    signals = [_sig("BTC/USDT", "long")]
    result = filter_signals_by_cooldown(signals, COOLDOWN_DAYS, journal, "futures_signals")

    assert len(result) == 1, (
        f"Cooldown sonrasi sinyal kabul edilmeli, ama {len(result)} kaldi"
    )


# ── Test 3 ─────────────────────────────────────────────────────────────────────

def test_different_sym_same_side_accepted():
    """Farklı symbol, aynı side → cooldown UYGULANMAZ, sinyal kabul.

    Senaryo: 1 gün önce BTC/USDT long fill. Bugün ETH/USDT long → ACCEPT.
    """
    fill_ts = datetime.now(timezone.utc) - timedelta(days=1)
    journal = _make_journal([{"symbol": "BTC/USDT", "side": "long", "ts": fill_ts}])

    signals = [_sig("ETH/USDT", "long")]
    result = filter_signals_by_cooldown(signals, COOLDOWN_DAYS, journal, "futures_signals")

    assert len(result) == 1, (
        f"Farkli symbol cooldown'a takilmamali, ama {len(result)} kaldi"
    )


# ── Test 4 ─────────────────────────────────────────────────────────────────────

def test_different_side_same_sym_accepted():
    """Aynı symbol, farklı side → cooldown UYGULANMAZ, sinyal kabul.

    Lab.py semantiği: key=(symbol, side) — long/short birbirinden bağımsız.
    Senaryo: 1 gün önce BTC/USDT long fill. Bugün BTC/USDT short → ACCEPT.
    """
    fill_ts = datetime.now(timezone.utc) - timedelta(days=1)
    journal = _make_journal([{"symbol": "BTC/USDT", "side": "long", "ts": fill_ts}])

    signals = [_sig("BTC/USDT", "short")]
    result = filter_signals_by_cooldown(signals, COOLDOWN_DAYS, journal, "futures_signals")

    assert len(result) == 1, (
        f"Farkli side cooldown'a takilmamali (lab.py: key=sym+side), "
        f"ama {len(result)} kaldi"
    )


# ── Test 5 ─────────────────────────────────────────────────────────────────────

def test_cooldown_disabled_in_yaml_no_filter():
    """cooldown_days=0 → filter no-op, tüm sinyaller geçmeli.

    Backward compat: YAML'da cooldown 0 veya devre dışı ise hiç filtreleme yok.
    """
    fill_ts = datetime.now(timezone.utc) - timedelta(days=0)  # şimdi
    journal = _make_journal([
        {"symbol": "BTC/USDT", "side": "long", "ts": fill_ts},
        {"symbol": "ETH/USDT", "side": "short", "ts": fill_ts},
    ])

    signals = [
        _sig("BTC/USDT", "long"),
        _sig("ETH/USDT", "short"),
        _sig("SOL/USDT", "long"),
    ]
    result = filter_signals_by_cooldown(signals, cooldown_days=0, journal_path=journal,
                                        table="futures_signals")

    assert len(result) == 3, (
        f"cooldown_days=0 → filter no-op, 3 sinyal beklenir, ama {len(result)} geldi"
    )


# ── Ekstra: farklı strategy aynı (sym, side) cooldown kapsar ──────────────────

def test_different_strategy_same_sym_side_still_rejected():
    """Farklı strategy, aynı (symbol, side) → lab.py semantiği: yine reject.

    Lab.py'de key=(sym, side), strategy farkı gözetilmez.
    """
    fill_ts = datetime.now(timezone.utc) - timedelta(days=1)
    journal = _make_journal([
        {"symbol": "XRP/USDT", "side": "long", "ts": fill_ts,
         "strategy": "brooks_failed_breakout"}
    ])

    # Farklı strategy, ama aynı (sym, side)
    signals = [_sig("XRP/USDT", "long", strategy="engulfing_continuation")]
    result = filter_signals_by_cooldown(signals, COOLDOWN_DAYS, journal, "futures_signals")

    assert len(result) == 0, (
        f"Lab.py semantigi: farkli strategy ayni (sym,side) cooldown kapsar. "
        f"Ama {len(result)} sinyal gecti"
    )
