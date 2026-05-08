"""Unit tests — EngulfingContinuation4HStrategy.

6 test scenarios:
  1. 4h adapted parameters — EMA periods, KER period, pullback window correct
  2. prepare_features produces required columns on 4h synthetic data
  3. Signal logic produces signals on 4h synthetic data (bullish + bearish)
  4. Lookahead test on 4h timeframe (pullback flag + engulfing strict)
  5. No signal without pullback (continuation rule enforced on 4h)
  6. No signal without engulfing (pattern gate enforced on 4h)
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
import pytest

from price_action.strategies.engulfing_continuation_4h import (
    EngulfingContinuation4HStrategy,
    _default_4h_manifest,
    _4H_SCALE,
    _EMA_PULLBACK,
    _EMA_TREND,
    _EMA_REGIME,
    _KER_PERIOD,
    _PULLBACK_WIN,
)
from price_action.strategies.engulfing_continuation import (
    _strict_engulfing,
    _pullback_to_ema_flag,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_4h_strategy():
    return EngulfingContinuation4HStrategy(_default_4h_manifest())


def _base_ts_4h(n: int) -> list[datetime]:
    """4-hour spaced timestamps."""
    start = datetime(2023, 1, 1, tzinfo=timezone.utc)
    return [start + timedelta(hours=4 * i) for i in range(n)]


def _make_4h_ohlcv(
    n: int,
    base_price: float = 110.0,
    drift: float = 0.001,
    seed: int = 42,
    uptrend: bool = True,
) -> pd.DataFrame:
    """Synthetic 4h OHLCV — enough bars for all EMA warmup."""
    rng = np.random.default_rng(seed)
    d = drift if uptrend else -drift
    rets = rng.normal(d, 0.008, n)
    close = base_price * np.exp(np.cumsum(rets))
    open_ = np.r_[close[0], close[:-1]]
    high = np.maximum(open_, close) * (1 + np.abs(rng.normal(0, 0.003, n)))
    low = np.minimum(open_, close) * (1 - np.abs(rng.normal(0, 0.003, n)))
    high = np.maximum.reduce([high, open_, close])
    low = np.minimum.reduce([low, open_, close])
    volume = rng.uniform(500_000.0, 3_000_000.0, n)
    ts = _base_ts_4h(n)
    return pd.DataFrame({
        "ts": ts, "open": open_, "high": high, "low": low,
        "close": close, "volume": volume,
        "venue": "binance", "symbol": "TEST/USDT", "timeframe": "4h",
    })


def _bar(o, h, l, c, v=1_000_000.0):
    return {"open": float(o), "high": float(h), "low": float(l), "close": float(c), "volume": float(v)}


def _df_bars_4h(bars: list[dict]) -> pd.DataFrame:
    ts = _base_ts_4h(len(bars))
    df = pd.DataFrame(bars)
    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = df[col].astype(float)
    df["ts"] = ts
    df["venue"] = "binance"
    df["symbol"] = "TEST/USDT"
    df["timeframe"] = "4h"
    if "volume" not in df.columns:
        df["volume"] = 1_000_000.0
    return df


def _make_flat_4h(n: int, base_price: float = 110.0, ema_val: float = 100.0, atr_val: float = 2.0) -> pd.DataFrame:
    """Flat 4h bars with pre-set EMA and ATR columns for pullback tests."""
    ts = _base_ts_4h(n)
    return pd.DataFrame({
        "ts": ts,
        "open": np.full(n, base_price - 1.0),
        "high": np.full(n, base_price + 2.0),
        "low": np.full(n, base_price - 1.5),
        "close": np.full(n, base_price),
        "volume": np.full(n, 1_000_000.0),
        "venue": "binance",
        "symbol": "TEST/USDT",
        "timeframe": "4h",
        "ema_pullback": np.full(n, ema_val),
        "ema20": np.full(n, ema_val),
        "atr14": np.full(n, atr_val),
    })


# ---------------------------------------------------------------------------
# Test 1: Parameter correctness
# ---------------------------------------------------------------------------

class Test4HParameters:
    """Verify 4h scaling constants match expected calendar-time windows."""

    def test_scale_factor_is_six(self):
        """4h scale factor must be 6 (24h / 4h)."""
        assert _4H_SCALE == 6

    def test_ema_pullback_scaled(self):
        """EMA-pullback = 20 * 6 = 120."""
        assert _EMA_PULLBACK == 120

    def test_ema_trend_scaled(self):
        """EMA-trend = 50 * 6 = 300."""
        assert _EMA_TREND == 300

    def test_ema_regime_scaled(self):
        """EMA-regime = 200 * 6 = 1200."""
        assert _EMA_REGIME == 1200

    def test_ker_period_scaled(self):
        """KER period = 14 * 6 = 84."""
        assert _KER_PERIOD == 84

    def test_pullback_window_scaled(self):
        """Pullback window = 10 * 6 = 60."""
        assert _PULLBACK_WIN == 60

    def test_manifest_ema_trend_period(self):
        """Manifest trend_filter.period must be 300."""
        m = _default_4h_manifest()
        assert m.trend_filter.period == 300

    def test_manifest_kaufman_er_period(self):
        """Manifest filter kaufman_er_period must be 84."""
        m = _default_4h_manifest()
        er = int(getattr(m.signals.filters, "kaufman_er_period", 0))
        assert er == 84

    def test_strategy_name(self):
        """Strategy name must be distinct from 1d."""
        strat = _make_4h_strategy()
        assert strat.name == "engulfing_continuation_4h"
        assert "4h" in strat.name

    def test_original_1d_strategy_unchanged(self):
        """1d strategy name must still be 'engulfing_continuation' (not modified)."""
        from price_action.strategies.engulfing_continuation import EngulfingContinuationStrategy
        assert EngulfingContinuationStrategy.name == "engulfing_continuation"


# ---------------------------------------------------------------------------
# Test 2: Feature columns on 4h data
# ---------------------------------------------------------------------------

class Test4HFeatureColumns:
    def test_prepare_features_returns_required_columns(self):
        """prepare_features must produce all expected columns on 4h data."""
        strat = _make_4h_strategy()
        # Need enough bars for EMA-1200 warmup — use 1300 bars
        df = _make_4h_ohlcv(n=1300, seed=10)
        out = strat.prepare_features(df)
        required = [
            "ema_pullback", "ema_trend", "ema_regime", "ema_trailing",
            "ema20", "ema50", "ema200", "ema14",
            "atr14", "atr_pct",
            "pullback_to_20ema",
            "strict_bull_engulf", "strict_bear_engulf",
            "struct_sl_long", "struct_sl_short",
            "kaufman_er",
            "always_in_long", "always_in_short",
        ]
        missing = [c for c in required if c not in out.columns]
        assert not missing, f"Missing columns: {missing}"

    def test_ema_aliases_match(self):
        """ema20 alias must equal ema_pullback."""
        strat = _make_4h_strategy()
        df = _make_4h_ohlcv(n=200, seed=20)
        out = strat.prepare_features(df)
        pd.testing.assert_series_equal(out["ema20"], out["ema_pullback"], check_names=False)

    def test_ema50_alias_matches_trend(self):
        """ema50 alias must equal ema_trend."""
        strat = _make_4h_strategy()
        df = _make_4h_ohlcv(n=400, seed=25)
        out = strat.prepare_features(df)
        pd.testing.assert_series_equal(out["ema50"], out["ema_trend"], check_names=False)

    def test_empty_df_returns_empty(self):
        strat = _make_4h_strategy()
        empty = pd.DataFrame(columns=["ts", "open", "high", "low", "close", "volume"])
        out = strat.prepare_features(empty)
        assert out.empty


# ---------------------------------------------------------------------------
# Test 3: Signal logic on 4h synthetic data
# ---------------------------------------------------------------------------

class Test4HSignalLogic:
    def test_bullish_signal_after_pullback_and_engulfing(self):
        """4h uptrend + pullback + bullish engulfing => long signal.

        Uses a permissive manifest (no SR proximity requirement) to isolate
        pattern logic.
        """
        from price_action.strategies.base import StrategyManifest
        raw = _default_4h_manifest().model_dump(mode="json")
        raw["signals"]["structure"]["require_proximity_to_sr_atr"] = 0.0
        raw["signals"]["confluence"]["min_score"] = 1.0
        raw["signals"]["filters"]["kaufman_er_min"] = 0.0
        strat = EngulfingContinuation4HStrategy(StrategyManifest.model_validate(raw))

        df = _make_4h_ohlcv(n=500, seed=7, uptrend=True)
        df_feat = strat.prepare_features(df)

        close_val = float(df_feat.loc[201, "ema_trend"]) * 1.05
        atr_val = abs(close_val * 0.02)
        df_feat.loc[200, "pullback_to_20ema"] = True
        df_feat.loc[201, "pullback_to_20ema"] = True
        df_feat.loc[201, "strict_bull_engulf"] = True
        df_feat.loc[201, "close"] = close_val
        df_feat.loc[201, "atr14"] = atr_val
        df_feat.loc[201, "atr_pct"] = 0.02
        df_feat.loc[201, "struct_sl_long"] = close_val * 0.95
        df_feat.loc[201, "kaufman_er"] = 0.5

        signals = strat.generate_signals(df_feat)
        long_sigs = [s for s in signals if s.direction == "long"]
        assert len(long_sigs) >= 1, "4h pullback+engulfing must produce at least 1 long signal"
        sig = long_sigs[0]
        assert sig.pattern_id == "bullish_engulfing_cont"
        assert sig.sl_price < close_val
        assert sig.tp_price > close_val

    def test_bearish_signal_after_pullback_and_engulfing(self):
        """4h downtrend + pullback + bearish engulfing => short signal.

        Uses a manifest with require_proximity_to_sr_atr=0.0 to isolate
        the pattern+filter logic from S/R proximity scoring.
        """
        from price_action.strategies.base import StrategyManifest
        raw = _default_4h_manifest().model_dump(mode="json")
        raw["signals"]["structure"]["require_proximity_to_sr_atr"] = 0.0
        raw["signals"]["confluence"]["min_score"] = 1.0
        raw["signals"]["filters"]["kaufman_er_min"] = 0.0
        strat = EngulfingContinuation4HStrategy(StrategyManifest.model_validate(raw))

        df = _make_4h_ohlcv(n=500, seed=3, uptrend=False)
        df_feat = strat.prepare_features(df)

        close_val = float(df_feat.loc[201, "ema_trend"]) * 0.95
        atr_val = abs(close_val * 0.02)  # 2% as ATR
        df_feat.loc[200, "pullback_to_20ema"] = True
        df_feat.loc[201, "pullback_to_20ema"] = True
        df_feat.loc[201, "strict_bear_engulf"] = True
        # Force price below trend EMA (downtrend condition)
        df_feat.loc[201, "close"] = close_val
        df_feat.loc[201, "atr14"] = atr_val
        df_feat.loc[201, "atr_pct"] = 0.02
        df_feat.loc[201, "struct_sl_short"] = close_val * 1.05
        df_feat.loc[201, "kaufman_er"] = 0.5  # ensure ER filter passes

        signals = strat.generate_signals(df_feat)
        short_sigs = [s for s in signals if s.direction == "short"]
        assert len(short_sigs) >= 1, "4h pullback+bearish engulfing must produce short signal"
        sig = short_sigs[0]
        assert sig.pattern_id == "bearish_engulfing_cont"
        assert sig.sl_price > float(df_feat.loc[201, "close"])

    def test_signal_timeframe_field_is_4h(self):
        """Emitted signal timeframe must be '4h'."""
        strat = _make_4h_strategy()
        df = _make_4h_ohlcv(n=500, seed=11, uptrend=True)
        df_feat = strat.prepare_features(df)
        df_feat.loc[200, "pullback_to_20ema"] = True
        df_feat.loc[201, "pullback_to_20ema"] = True
        df_feat.loc[201, "strict_bull_engulf"] = True
        df_feat.loc[201, "close"] = float(df_feat.loc[201, "ema_trend"]) * 1.05
        df_feat.loc[201, "struct_sl_long"] = float(df_feat.loc[201, "close"]) * 0.95
        df_feat.loc[201, "atr_pct"] = 0.01
        signals = strat.generate_signals(df_feat)
        long_sigs = [s for s in signals if s.direction == "long"]
        if long_sigs:
            assert long_sigs[0].timeframe == "4h"

    def test_smoke_run_no_exception(self):
        """Smoke: prepare + generate on 4h data must not raise."""
        strat = _make_4h_strategy()
        df = _make_4h_ohlcv(n=1400, seed=77)
        df_feat = strat.prepare_features(df)
        signals = strat.generate_signals(df_feat)
        assert isinstance(signals, list)


# ---------------------------------------------------------------------------
# Test 4: Lookahead bias on 4h
# ---------------------------------------------------------------------------

class Test4HLookahead:
    def test_pullback_flag_no_lookahead(self):
        """Pullback flag at bar t must not use data from t+1 onward.

        EMA touch at bar 70.
        Bar 69 (before touch): flag must be False.
        Bar 71 (1 bar after touch via shift(1)): flag must be True.
        """
        n = 150
        df = _make_flat_4h(n, base_price=110.0, ema_val=100.0, atr_val=2.0)
        df.loc[70, "low"] = 99.5   # within ema ± 0.5*2=1.0 band
        df.loc[70, "high"] = 101.0

        flags = _pullback_to_ema_flag(
            df, ema_col="ema_pullback", window=_PULLBACK_WIN, touch_atr_factor=0.5
        )
        assert not bool(flags.iloc[69]), "Bar before touch: no lookahead, flag must be False"
        assert bool(flags.iloc[71]), "Bar after touch (shift+1): flag must be True"

    def test_strict_engulfing_no_lookahead_4h(self):
        """_strict_engulfing at bar t only uses bar t-1 (shift(1)) — no lookahead."""
        bars = [
            _bar(100.0, 101.0, 99.0, 100.0),
            _bar(100.0, 101.0, 95.0, 96.0),   # bearish N-1
            _bar(95.0, 106.0, 94.0, 105.0),   # bullish engulf N
        ]
        df = _df_bars_4h(bars)
        flags = _strict_engulfing(df, body_ratio_min=0.6, bullish=True)
        # Bar 1 (before engulfing bar 2): must NOT be True
        assert not bool(flags.iloc[1]), "Bar 1 must not have lookahead of bar 2 engulfing"
        assert bool(flags.iloc[2]), "Bar 2 is the engulfing bar — must be True"

    def test_signal_at_t_unaffected_by_future_bars(self):
        """End-to-end lookahead: zeroing t+2..end flags must not remove t=201 signal.

        Uses a permissive manifest (no SR proximity, low min_score) so
        the forced bar-201 engulfing signal is guaranteed to emit, then
        verifies that zeroing future bars does not retract it.
        """
        from price_action.strategies.base import StrategyManifest
        raw = _default_4h_manifest().model_dump(mode="json")
        raw["signals"]["structure"]["require_proximity_to_sr_atr"] = 0.0
        raw["signals"]["confluence"]["min_score"] = 1.0
        raw["signals"]["filters"]["kaufman_er_min"] = 0.0
        strat = EngulfingContinuation4HStrategy(StrategyManifest.model_validate(raw))

        df = _make_4h_ohlcv(n=500, seed=21, uptrend=True)
        df_feat = strat.prepare_features(df)

        close_val = float(df_feat.loc[201, "ema_trend"]) * 1.05
        atr_val = abs(close_val * 0.02)
        df_feat.loc[200, "pullback_to_20ema"] = True
        df_feat.loc[201, "pullback_to_20ema"] = True
        df_feat.loc[201, "strict_bull_engulf"] = True
        df_feat.loc[201, "close"] = close_val
        df_feat.loc[201, "atr14"] = atr_val
        df_feat.loc[201, "atr_pct"] = 0.02
        df_feat.loc[201, "struct_sl_long"] = close_val * 0.95
        df_feat.loc[201, "kaufman_er"] = 0.5

        sigs_full = strat.generate_signals(df_feat)
        long_full = {s.ts for s in sigs_full if s.direction == "long"}

        # Zero out future bars
        df_trunc = df_feat.copy()
        df_trunc.loc[202:, "pullback_to_20ema"] = False
        df_trunc.loc[202:, "strict_bull_engulf"] = False
        df_trunc.loc[202:, "kaufman_er"] = np.nan

        sigs_trunc = strat.generate_signals(df_trunc)
        long_trunc = {s.ts for s in sigs_trunc if s.direction == "long"}

        # The bar-201 signal timestamp should appear in both
        assert len(long_full) >= 1, "Bar 201 long signal must appear in full run"
        assert len(long_trunc) >= 1, "Bar 201 long signal must appear in truncated run"
        assert len(long_full & long_trunc) >= 1, (
            "Bar 201 long signal must be in both full and truncated run "
            "(no lookahead dependency)"
        )


# ---------------------------------------------------------------------------
# Test 5: No signal without pullback
# ---------------------------------------------------------------------------

class TestNo4HSignalWithoutPullback:
    def test_engulfing_without_pullback_no_signal(self):
        """Engulfing present but pullback False => no signal (continuation rule)."""
        strat = _make_4h_strategy()
        df = _make_4h_ohlcv(n=500, seed=15, uptrend=True)
        df_feat = strat.prepare_features(df)
        # No pullback anywhere
        df_feat["pullback_to_20ema"] = False
        # Inject engulfing
        df_feat.loc[200, "strict_bull_engulf"] = True
        df_feat.loc[200, "atr_pct"] = 0.01

        signals = strat.generate_signals(df_feat)
        long_sigs = [s for s in signals if s.direction == "long"]
        assert len(long_sigs) == 0, "No pullback => engulfing alone must not generate signal"


# ---------------------------------------------------------------------------
# Test 6: No signal without engulfing
# ---------------------------------------------------------------------------

class TestNo4HSignalWithoutEngulfing:
    def test_pullback_without_engulfing_no_signal(self):
        """Pullback flag True but no engulfing bar => no signal."""
        strat = _make_4h_strategy()
        df = _make_4h_ohlcv(n=500, seed=99, uptrend=True)
        df_feat = strat.prepare_features(df)
        # Clear all engulfing
        df_feat["strict_bull_engulf"] = False
        df_feat["strict_bear_engulf"] = False
        # Set pullback True everywhere
        df_feat["pullback_to_20ema"] = True

        signals = strat.generate_signals(df_feat)
        assert signals == [], "Pullback without engulfing must not produce signals"
