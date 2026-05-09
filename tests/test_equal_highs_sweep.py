"""Unit + integration testleri — EqualHighsSweepStrategy (H-2).

Test planı (8 test):
  1. Boş DataFrame → sinyal yok, çökmez.
  2. EQH pool tespiti — eşit swing high'lar NaN değil döndürmeli.
  3. EQL pool tespiti — eşit swing low'lar NaN değil döndürmeli.
  4. Sweep + reversal → SHORT sinyal üretilmeli.
  5. Sweep + reversal → LONG sinyal üretilmeli (mirror).
  6. Pool yok → sinyal üretilmemeli.
  7. Sweep var ama reclaim yok (gerçek kırılma) → sinyal üretilmemeli.
  8. Backtest entegrasyon — motor üzerinde çalışır, n_trades >= 0.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
import pytest

from price_action.strategies.equal_highs_sweep import (
    EqualHighsSweepStrategy,
    _default_manifest,
    _detect_equal_highs,
)


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------

def _base_df(n: int = 120, seed: int = 99) -> pd.DataFrame:
    """Sentetik OHLCV — düz fiyat (ATR hesaplanabilsin)."""
    rng = np.random.default_rng(seed)
    base_ts = datetime(2023, 1, 1, tzinfo=timezone.utc)
    ts = [base_ts + timedelta(days=i) for i in range(n)]
    close = 1000.0 + np.cumsum(rng.normal(0, 5, n))
    open_ = np.r_[close[0], close[:-1]]
    high = np.maximum(open_, close) + rng.uniform(1, 10, n)
    low = np.minimum(open_, close) - rng.uniform(1, 10, n)
    vol = rng.uniform(1_000, 5_000, n)
    return pd.DataFrame({
        "venue": "binance",
        "symbol": "TEST/USDT",
        "timeframe": "1d",
        "ts": ts,
        "open": open_,
        "high": high,
        "low": low,
        "close": close,
        "volume": vol,
    })


def _make_strategy() -> EqualHighsSweepStrategy:
    return EqualHighsSweepStrategy(_default_manifest())


# ---------------------------------------------------------------------------
# Test 1: Boş DataFrame → no crash, empty signals
# ---------------------------------------------------------------------------
def test_empty_dataframe_returns_empty_signals():
    strat = _make_strategy()
    empty = pd.DataFrame(
        columns=["venue", "symbol", "timeframe", "ts", "open", "high", "low", "close", "volume"]
    )
    sigs = strat.generate_signals(empty)
    assert sigs == []


# ---------------------------------------------------------------------------
# Test 2: EQH pool tespiti
# ---------------------------------------------------------------------------
def test_eqh_pool_detected_when_equal_highs_present():
    """İki aynı swing high varsa eqh_level NaN olmamalı."""
    df = _base_df(n=120)
    strat = _make_strategy()
    df_f = strat.prepare_features(df)

    # Manuel olarak 2 aynı swing high yerleştir
    # Swing high oluşması için: bar[i] high > komşularından büyük olmalı (fractal n=3)
    # bar 20 ve bar 40'a aynı high seviyesi koy
    peak_price = float(df_f["close"].mean()) + 50.0
    # Her iki tarafı da daha düşük yap (fractal koşulu)
    for idx in [17, 18, 19, 20, 21, 22, 23]:
        df_f.loc[idx, "high"] = peak_price - 20 + (5 if idx == 20 else 0)
    for idx in [37, 38, 39, 40, 41, 42, 43]:
        df_f.loc[idx, "high"] = peak_price - 20 + (5 if idx == 40 else 0)

    # Hem 20 hem 40'ın high'ı yakın (fark sıfır) → fractal koşulu da sağlanmış
    # _detect_equal_highs tekrar çağır
    from price_action.strategies.equal_highs_sweep import _detect_equal_highs
    eqh, _ = _detect_equal_highs(df_f, lookback=30, tolerance_atr=0.15, n_fractal=3)

    # Bar 43+ (swing teyidi sonrası) için eqh_level dolu olmalı
    late_bars = eqh.iloc[50:]
    assert late_bars.notna().any(), "EQH pool tespit edilemedi."


# ---------------------------------------------------------------------------
# Test 3: EQL pool tespiti
# ---------------------------------------------------------------------------
def test_eql_pool_detected_when_equal_lows_present():
    """İki aynı swing low varsa eql_level NaN olmamalı."""
    df = _base_df(n=120)
    strat = _make_strategy()
    df_f = strat.prepare_features(df)

    trough_price = float(df_f["close"].mean()) - 50.0
    for idx in [17, 18, 19, 20, 21, 22, 23]:
        df_f.loc[idx, "low"] = trough_price + 20 - (5 if idx == 20 else 0)
    for idx in [37, 38, 39, 40, 41, 42, 43]:
        df_f.loc[idx, "low"] = trough_price + 20 - (5 if idx == 40 else 0)

    from price_action.strategies.equal_highs_sweep import _detect_equal_highs
    _, eql = _detect_equal_highs(df_f, lookback=30, tolerance_atr=0.15, n_fractal=3)

    late_bars = eql.iloc[50:]
    assert late_bars.notna().any(), "EQL pool tespit edilemedi."


# ---------------------------------------------------------------------------
# Test 4: EQH sweep → SHORT sinyal
# ---------------------------------------------------------------------------
def test_eqh_sweep_generates_short_signal():
    """EQH sweep + reclaim → SHORT sinyal üretilmeli."""
    strat = _make_strategy()
    df = _base_df(n=120)
    df_f = strat.prepare_features(df)

    # ATR hesaplanmış olmalı
    atr_val = float(df_f["atr14"].dropna().iloc[-1])
    pool_level = float(df_f["close"].mean()) + 30.0
    tol = atr_val * 0.10  # toleransın içinde

    # İki swing high oluştur (bar 20 ve bar 40)
    for idx in [17, 18, 19, 21, 22, 23]:
        df_f.loc[idx, "high"] = pool_level - 15
    df_f.loc[20, "high"] = pool_level
    for idx in [37, 38, 39, 41, 42, 43]:
        df_f.loc[idx, "high"] = pool_level - 15
    df_f.loc[40, "high"] = pool_level + tol * 0.5  # eşit (tol içinde)

    # EQH hesapla
    eqh, _ = _detect_equal_highs(df_f, lookback=30, tolerance_atr=0.15, n_fractal=3)
    df_f["eqh_level"] = eqh
    _, eql2 = _detect_equal_highs(df_f, lookback=30, tolerance_atr=0.15, n_fractal=3)
    df_f["eql_level"] = eql2

    # Pool seviyesini bilinen bir bar'a sabitle
    target_bar = 80
    active_pool = pool_level
    df_f.loc[target_bar, "eqh_level"] = active_pool

    # Sweep bar: high > pool, close < pool
    df_f.loc[target_bar, "high"] = active_pool + atr_val * 0.3
    df_f.loc[target_bar, "close"] = active_pool - atr_val * 0.2
    df_f.loc[target_bar, "open"] = active_pool - atr_val * 0.05
    # Sanity: high >= max(open,close)
    df_f.loc[target_bar, "high"] = max(
        df_f.loc[target_bar, "high"],
        df_f.loc[target_bar, "open"],
        df_f.loc[target_bar, "close"],
    )

    sigs = strat.generate_signals(df_f)
    short_sigs = [s for s in sigs if s.direction == "short"]
    assert len(short_sigs) >= 1, f"SHORT sinyal bekleniyor. Üretilen: {sigs}"
    sig = short_sigs[0]
    assert sig.pattern_id == "eqh_sweep_short"
    assert sig.sl_price > sig.tp_price, "Short SL > TP olmalı (short pozisyon)"


# ---------------------------------------------------------------------------
# Test 5: EQL sweep → LONG sinyal (mirror)
# ---------------------------------------------------------------------------
def test_eql_sweep_generates_long_signal():
    """EQL sweep + reclaim → LONG sinyal üretilmeli."""
    strat = _make_strategy()
    df = _base_df(n=120)
    df_f = strat.prepare_features(df)

    atr_val = float(df_f["atr14"].dropna().iloc[-1])
    pool_level = float(df_f["close"].mean()) - 30.0

    target_bar = 80
    df_f["eqh_level"] = np.nan
    df_f["eql_level"] = np.nan
    df_f.loc[target_bar, "eql_level"] = pool_level

    # EQL sweep: low < pool, close > pool
    df_f.loc[target_bar, "low"] = pool_level - atr_val * 0.3
    df_f.loc[target_bar, "close"] = pool_level + atr_val * 0.2
    df_f.loc[target_bar, "open"] = pool_level + atr_val * 0.05
    # Sanity: low <= min(open, close)
    df_f.loc[target_bar, "low"] = min(
        df_f.loc[target_bar, "low"],
        df_f.loc[target_bar, "open"],
        df_f.loc[target_bar, "close"],
    )

    sigs = strat.generate_signals(df_f)
    long_sigs = [s for s in sigs if s.direction == "long"]
    assert len(long_sigs) >= 1, f"LONG sinyal bekleniyor. Üretilen: {sigs}"
    sig = long_sigs[0]
    assert sig.pattern_id == "eql_sweep_long"
    assert sig.sl_price < sig.tp_price, "Long SL < TP olmalı"


# ---------------------------------------------------------------------------
# Test 6: Pool yok → sinyal üretilmemeli
# ---------------------------------------------------------------------------
def test_no_pool_no_signal():
    """EQH/EQL pool yoksa sinyal üretilmemeli."""
    strat = _make_strategy()
    df = _base_df(n=120)
    df_f = strat.prepare_features(df)

    # Tüm pool seviyelerini NaN yap
    df_f["eqh_level"] = np.nan
    df_f["eql_level"] = np.nan

    sigs = strat.generate_signals(df_f)
    assert sigs == [], f"Pool yok → sinyal beklenmez. Alınan: {sigs}"


# ---------------------------------------------------------------------------
# Test 7: Sweep var ama close > pool (reclaim yok) → sinyal yok
# ---------------------------------------------------------------------------
def test_no_reclaim_no_signal():
    """Fiyat pool'u geçti ama geri dönmedi (gerçek kırılma) → sinyal yok."""
    strat = _make_strategy()
    df = _base_df(n=120)
    df_f = strat.prepare_features(df)

    atr_val = float(df_f["atr14"].dropna().iloc[-1])
    pool_level = float(df_f["close"].mean()) + 30.0
    target_bar = 80

    df_f["eqh_level"] = np.nan
    df_f["eql_level"] = np.nan
    df_f.loc[target_bar, "eqh_level"] = pool_level

    # high > pool AMA close de > pool (reclaim yok → gerçek kırılma)
    df_f.loc[target_bar, "high"] = pool_level + atr_val * 0.5
    df_f.loc[target_bar, "close"] = pool_level + atr_val * 0.3  # close ÜSTÜNDE kaldı
    df_f.loc[target_bar, "open"] = pool_level + atr_val * 0.1

    sigs = strat.generate_signals(df_f)
    short_sigs = [s for s in sigs if s.direction == "short"]
    assert short_sigs == [], f"Reclaim yok → SHORT sinyal beklenmez. Alınan: {short_sigs}"


# ---------------------------------------------------------------------------
# Test 8: Backtest engine entegrasyon — çökmemeli
# ---------------------------------------------------------------------------
@pytest.mark.slow
def test_backtest_engine_integration():
    """BacktestEngine üstünde EqualHighsSweepStrategy çalışır."""
    from datetime import timezone
    from price_action.backtest.engine import BacktestEngine

    rng = np.random.default_rng(42)
    n = 600
    base_ts = datetime(2022, 1, 1, tzinfo=timezone.utc)
    ts = [base_ts + timedelta(days=i) for i in range(n)]
    rets = rng.normal(0.0005, 0.018, n)
    close = 30_000.0 * np.exp(np.cumsum(rets))
    open_ = np.r_[close[0], close[:-1]]
    high = np.maximum(open_, close) * (1 + np.abs(rng.normal(0, 0.006, n)))
    low = np.minimum(open_, close) * (1 - np.abs(rng.normal(0, 0.006, n)))
    vol = rng.uniform(1_000_000, 5_000_000, n)

    df = pd.DataFrame({
        "venue": "binance",
        "symbol": "BTC/USDT",
        "timeframe": "1d",
        "ts": ts,
        "open": open_,
        "high": high,
        "low": low,
        "close": close,
        "volume": vol,
    })

    strat = _make_strategy()

    def loader(sym, tf, start, end):
        return df.copy()

    engine = BacktestEngine(risk_officer=None, store_load=loader)
    result = engine.run(
        strat,
        ["BTC/USDT"],
        start=datetime(2022, 1, 1, tzinfo=timezone.utc),
        end=datetime(2023, 8, 31, tzinfo=timezone.utc),
        timeframe="1d",
        initial_capital=10_000.0,
        fees={"taker": 0.00075, "maker": -0.0001},
        slippage_bps=5.0,
    )

    assert result is not None
    assert result.n_trades >= 0
    assert "win_rate" in result.kpis
    assert result.elapsed_sec >= 0
