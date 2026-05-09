"""Realistic per-symbol slippage — 5 temel test.

1. SlippageModel.get_bps — notional yukseldikce slippage artar
2. SlippageModel.summary — tum semboller donulur, kategori dogru
3. BacktestEngine — symbol_slippage_map override geriye uyumlu
4. BacktestEngine — high-slip sembol flat'ten dusuk P&L uretir
5. build_slippage_map — live=False fallback degerleri kullanir
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Dict

import numpy as np
import pandas as pd
import pytest

from price_action.backtest.slippage import (
    FALLBACK_SLIPPAGE_BPS,
    SlippageModel,
    build_slippage_map,
    _depth_weighted_price,
    _notional_multiplier,
)
from price_action.backtest.engine import BacktestEngine
from price_action.strategies.base import StrategyManifest
from price_action.strategies.classic_pa import ClassicPriceActionStrategy


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _synthetic_ohlcv(n: int = 400, seed: int = 42, symbol: str = "TEST/USDT") -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    base_ts = datetime(2022, 1, 1, tzinfo=timezone.utc)
    ts = [base_ts + timedelta(days=i) for i in range(n)]
    rets = rng.normal(0.001, 0.02, n)
    close = 100 * np.exp(np.cumsum(rets))
    open_ = np.r_[close[0], close[:-1]]
    high = np.maximum(open_, close) * (1 + np.abs(rng.normal(0, 0.005, n)))
    low = np.minimum(open_, close) * (1 - np.abs(rng.normal(0, 0.005, n)))
    vol = rng.uniform(1_000_000, 5_000_000, n)
    return pd.DataFrame({
        "venue": "binance", "symbol": symbol, "timeframe": "1d", "ts": ts,
        "open": open_, "high": high, "low": low, "close": close, "volume": vol,
    })


def _make_strategy() -> ClassicPriceActionStrategy:
    raw = {
        "name": "slip_test_pa", "version": "0.0.1",
        "trend_filter": {"type": "ema", "period": 20, "required": False},
        "signals": {
            "patterns": [
                {"id": "bullish_engulfing", "enabled": True, "weight": 1.5},
                {"id": "bearish_engulfing", "enabled": True, "weight": 1.5},
            ],
            "structure": {
                "swing": {"fractal_n": 2},
                "support_resistance": {
                    "lookback_bars": 100, "cluster_atr_multiplier": 0.5,
                    "min_touches": 2, "max_age_bars": 100,
                },
                "require_proximity_to_sr_atr": 0.0,
            },
            "filters": {"atr_min_pct": 0.0},
            "confluence": {"method": "weighted_sum", "min_score": 1.0, "bonus_if_at_sr": 0.0},
        },
        "risk": {
            "stop_loss": {"atr_multiplier": 2.0},
            "take_profit": {"primary_R": 2.0},
        },
    }
    return ClassicPriceActionStrategy(StrategyManifest.model_validate(raw))


# ---------------------------------------------------------------------------
# Test 1: SlippageModel — notional yukseldikce slippage artar
# ---------------------------------------------------------------------------

def test_slippage_model_notional_scaling():
    """Buyuk notional daha yuksek slippage bps uretmeli."""
    model = SlippageModel(
        symbol_slippage_map={"BTC/USDT": 5.0, "DOGE/USDT": 20.0},
        default_bps=10.0,
    )
    # BTC: 1K < 5K < 10K
    bps_1k = model.get_bps("BTC/USDT", notional=1_000)
    bps_5k = model.get_bps("BTC/USDT", notional=5_000)
    bps_10k = model.get_bps("BTC/USDT", notional=10_000)
    assert bps_1k < bps_5k < bps_10k, "Notional artinca slippage artmali"

    # DOGE: her seviyede BTC'den yuksek
    assert model.get_bps("DOGE/USDT", notional=1_000) > model.get_bps("BTC/USDT", notional=1_000)


# ---------------------------------------------------------------------------
# Test 2: SlippageModel.summary — kategori ve alan dogrulugu
# ---------------------------------------------------------------------------

def test_slippage_model_summary_structure():
    """summary() dogru alanlarla donmeli, kategori eslemesi tutarli."""
    SYMBOLS = ["BTC/USDT", "ETH/USDT", "DOGE/USDT"]
    model = SlippageModel(
        symbol_slippage_map={s: FALLBACK_SLIPPAGE_BPS[s] for s in SYMBOLS},
        default_bps=15.0,
    )
    rows = model.summary()
    assert len(rows) == 3

    for row in rows:
        assert "symbol" in row
        assert "spread_bps_1k" in row
        assert "slippage_bps_5k" in row
        assert "slippage_bps_10k" in row
        assert "category" in row
        # 5K >= 1K
        assert row["slippage_bps_5k"] >= row["spread_bps_1k"]
        # 10K >= 5K
        assert row["slippage_bps_10k"] >= row["slippage_bps_5k"]

    # BTC large-cap, DOGE small-cap
    cats = {r["symbol"]: r["category"] for r in rows}
    assert cats["BTC/USDT"] == "large-cap"
    assert cats["DOGE/USDT"] == "small-cap"


# ---------------------------------------------------------------------------
# Test 3: BacktestEngine — symbol_slippage_map geriye uyumlu (map=None)
# ---------------------------------------------------------------------------

def test_engine_symbol_slippage_map_backward_compat():
    """symbol_slippage_map=None ile engine eski davranisi korumali."""
    df = _synthetic_ohlcv()

    def loader(symbol, tf, start, end):
        return df.copy()

    strat = _make_strategy()
    engine = BacktestEngine(risk_officer=None, store_load=loader)

    # map olmadan — flat 5bps
    result = engine.run(
        strat, ["TEST/USDT"],
        start=datetime(2022, 1, 1, tzinfo=timezone.utc),
        end=datetime(2023, 1, 1, tzinfo=timezone.utc),
        timeframe="1d",
        initial_capital=10_000,
        slippage_bps=5.0,
        symbol_slippage_map=None,
    )
    assert result.strategy_name == "slip_test_pa"
    assert result.symbol_slippage_map == {}     # bos dict dondurulmeli
    assert "sharpe" in result.kpis


# ---------------------------------------------------------------------------
# Test 4: BacktestEngine — yuksek slippage azalan veya esit P&L
# ---------------------------------------------------------------------------

def test_engine_high_slippage_reduces_pnl():
    """30bps slippage, 5bps'ten dusuk ya da esit P&L uretmeli."""
    df = _synthetic_ohlcv(seed=99)

    def loader(symbol, tf, start, end):
        return df.copy()

    strat = _make_strategy()
    engine = BacktestEngine(risk_officer=None, store_load=loader)

    shared = dict(
        strategy=strat,
        universe=["TEST/USDT"],
        start=datetime(2022, 1, 1, tzinfo=timezone.utc),
        end=datetime(2023, 1, 1, tzinfo=timezone.utc),
        timeframe="1d",
        initial_capital=10_000,
    )

    r_low = engine.run(**shared, slippage_bps=5.0)
    r_high = engine.run(**shared, slippage_bps=30.0)

    eq_low = r_low.equity_curve.iloc[-1]
    eq_high = r_high.equity_curve.iloc[-1]

    # Yuksek slippage ya daha az kazanmali ya da ayni (sifir trade durumunda)
    assert eq_high <= eq_low + 1e-6, (
        f"Yuksek slippage ({eq_high:.2f}) flat'ten ({eq_low:.2f}) fazla olamaz"
    )


# ---------------------------------------------------------------------------
# Test 5: build_slippage_map — live=False fallback degerler
# ---------------------------------------------------------------------------

def test_build_slippage_map_fallback():
    """live=False -> FALLBACK_SLIPPAGE_BPS kullanilmali."""
    SYMS = ["BTC/USDT", "ETH/USDT", "DOGE/USDT"]
    result = build_slippage_map(SYMS, notional_ref=1_000, use_live=False)

    assert set(result.keys()) == set(SYMS)
    for sym in SYMS:
        expected = FALLBACK_SLIPPAGE_BPS[sym]
        assert abs(result[sym] - expected) < 1e-9, (
            f"{sym}: beklenen {expected} bps, alinan {result[sym]} bps"
        )
    # BTC < DOGE (large-cap < small-cap)
    assert result["BTC/USDT"] < result["DOGE/USDT"]


# ---------------------------------------------------------------------------
# Bonus: depth_weighted_price mantigi
# ---------------------------------------------------------------------------

def test_depth_weighted_price_basic():
    """Tek seviye ask: fill price = level price."""
    asks = [(100.0, 1000.0)]   # 1000 birim $100'dan
    fill = _depth_weighted_price(asks, notional=500.0, side="buy")
    assert abs(fill - 100.0) < 1e-6

    # Iki seviye: $500 @ 100, $500 @ 101
    asks2 = [(100.0, 5.0), (101.0, 10.0)]  # qty base
    fill2 = _depth_weighted_price(asks2, notional=1_005.0, side="buy")
    # 500 @ 100 + 505/101 = 5 birim @ 100 + 5 birim @ 101
    # fill = (500 + 505) / 10 = ~100.5
    assert 100.0 <= fill2 <= 101.0


def test_notional_multiplier_monotone():
    """Notional arttikca carpan da artar ya da ayni."""
    prev = _notional_multiplier(0)
    for n in [500, 1_000, 2_000, 5_000, 10_000, 50_000]:
        curr = _notional_multiplier(n)
        assert curr >= prev, f"n={n}: {curr} < {prev}"
        prev = curr
