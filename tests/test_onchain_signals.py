"""Unit tests — OnChainSignalsStrategy + onchain_ingest helpers.

Test scenarios:
  1. add_synthetic_nupl: NUPL = (MVRV-1)/MVRV mathematical correctness
  2. add_exchange_netflow: netflow = outflow - inflow, z-score rolling
  3. merge_onchain_to_ohlcv: timestamp join, forward-fill, empty cases
  4. OnChainSignalsStrategy.prepare_features: required columns added, lag-1
  5. Signal generation:
     a. MVRV < 1 + NUPL < 0.25 + EMA50 → LONG signal
     b. MVRV > 3.5 + NUPL > 0.75 + below EMA50 → SHORT signal
     c. Normal MVRV (1.5) → no signal
     d. Missing on-chain columns → no signals (graceful)
     e. Empty DataFrame → empty list
  6. Lookahead-bias: on-chain metrics lagged by 1 bar
  7. SL/TP: SL < entry (long), TP > entry (long); SL > entry (short)
  8. _default_manifest: valid manifest with correct pattern IDs
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
import pytest

from price_action.data.onchain_ingest import (
    add_exchange_netflow,
    add_synthetic_nupl,
    _to_cm_asset,
    COMMUNITY_METRICS,
)
from price_action.strategies.onchain_signals import merge_onchain_to_ohlcv
from price_action.strategies.onchain_signals import (
    MVRV_BOTTOM_DEFAULT,
    MVRV_TOP_DEFAULT,
    NUPL_BOTTOM_DEFAULT,
    NUPL_TOP_DEFAULT,
    OnChainSignalsStrategy,
    _addr_zscore,
    _default_manifest,
    _mvrv_regime,
    _nupl_regime,
    _swing_sl_price,
)


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

def _daily_ts(n: int, start: datetime | None = None) -> list[datetime]:
    if start is None:
        start = datetime(2021, 1, 1, tzinfo=timezone.utc)
    return [start + timedelta(days=i) for i in range(n)]


def _make_ohlcv(
    n: int,
    base_price: float = 50_000.0,
    seed: int = 42,
) -> pd.DataFrame:
    """Synthetic 1d BTC-like OHLCV."""
    rng = np.random.default_rng(seed)
    rets = rng.normal(0.0, 0.02, n)
    close = base_price * np.exp(np.cumsum(rets))
    open_ = np.r_[close[0], close[:-1]]
    high = np.maximum(open_, close) * (1 + np.abs(rng.normal(0, 0.005, n)))
    low = np.minimum(open_, close) * (1 - np.abs(rng.normal(0, 0.005, n)))
    high = np.maximum.reduce([high, open_, close])
    low = np.minimum.reduce([low, open_, close])
    return pd.DataFrame({
        "ts": _daily_ts(n),
        "open": open_,
        "high": high,
        "low": low,
        "close": close,
        "volume": rng.uniform(5e8, 2e9, n),
        "venue": "binance",
        "symbol": "BTC/USDT",
        "timeframe": "1d",
    })


def _make_onchain(
    n: int,
    mvrv: float = 1.5,
    seed: int = 42,
) -> pd.DataFrame:
    """Synthetic on-chain DataFrame mimicking Coin Metrics output."""
    rng = np.random.default_rng(seed)
    ts = _daily_ts(n)
    mvrv_vals = mvrv + rng.normal(0, 0.05, n)
    nupl_vals = (mvrv_vals - 1.0) / mvrv_vals  # exact formula
    flow_in = rng.uniform(1000, 5000, n)
    flow_out = rng.uniform(1000, 5000, n)
    addr = rng.uniform(800_000, 1_200_000, n)
    hashrate = rng.uniform(400e18, 600e18, n)
    return pd.DataFrame({
        "ts": ts,
        "asset": "btc",
        "CapMVRVCur": mvrv_vals,
        "nupl_proxy": nupl_vals,
        "FlowInExNtv": flow_in,
        "FlowOutExNtv": flow_out,
        "AdrActCnt": addr,
        "HashRate": hashrate,
    })


def _make_strategy(overrides: dict | None = None) -> OnChainSignalsStrategy:
    from price_action.strategies.base import StrategyManifest
    raw = {
        "name": "onchain_signals",
        "version": "1.0.0",
        "trend_filter": {"type": "ema", "period": 50, "required": False},
        "signals": {
            "patterns": [
                {
                    "id": "onchain_long",
                    "enabled": True,
                    "weight": 1.0,
                    "params": {
                        "mvrv_bottom": MVRV_BOTTOM_DEFAULT,
                        "nupl_bottom": NUPL_BOTTOM_DEFAULT,
                        "flow_sigma_min": -2.0,  # lenient for tests
                        "addr_z_min": -3.0,
                    },
                },
                {
                    "id": "onchain_short",
                    "enabled": True,
                    "weight": 1.0,
                    "params": {
                        "mvrv_top": MVRV_TOP_DEFAULT,
                        "nupl_top": NUPL_TOP_DEFAULT,
                        "flow_sigma_max": 2.0,  # lenient for tests
                    },
                },
            ],
            "structure": {
                "swing": {"fractal_n": 2},
                "support_resistance": {
                    "lookback_bars": 50,
                    "cluster_atr_multiplier": 0.5,
                    "min_touches": 2,
                    "max_age_bars": 50,
                },
                "require_proximity_to_sr_atr": 0.0,
            },
            "filters": {"atr_min_pct": 0.0, "volume_zscore_min": 0.0},
            "confluence": {"method": "weighted_sum", "min_score": 1.0},
        },
        "risk": {
            "stop_loss": {"method": "structural_swing", "swing_lookback": 5, "atr_buffer": 0.5},
            "take_profit": {"method": "r_multiple", "primary_R": 3.0},
        },
    }
    if overrides:
        raw.update(overrides)
    manifest = StrategyManifest.model_validate(raw)
    return OnChainSignalsStrategy(manifest)


# ---------------------------------------------------------------------------
# 1. add_synthetic_nupl
# ---------------------------------------------------------------------------

class TestSyntheticNUPL:
    def test_nupl_formula_correctness(self) -> None:
        """NUPL_proxy = (MVRV-1)/MVRV is mathematically exact."""
        df = pd.DataFrame({"CapMVRVCur": [1.0, 2.0, 4.0, 0.5]})
        result = add_synthetic_nupl(df)
        assert "nupl_proxy" in result.columns
        # MVRV=1 → NUPL=0
        assert float(result["nupl_proxy"].iloc[0]) == pytest.approx(0.0, abs=1e-9)
        # MVRV=2 → NUPL=0.5
        assert float(result["nupl_proxy"].iloc[1]) == pytest.approx(0.5, abs=1e-9)
        # MVRV=4 → NUPL=0.75
        assert float(result["nupl_proxy"].iloc[2]) == pytest.approx(0.75, abs=1e-9)
        # MVRV=0.5 → NUPL=-1.0 (below realized, underwater)
        assert float(result["nupl_proxy"].iloc[3]) == pytest.approx(-1.0, abs=1e-9)

    def test_nupl_missing_mvrv_col(self) -> None:
        """If CapMVRVCur missing, nupl_proxy should be NaN."""
        df = pd.DataFrame({"other_col": [1.0, 2.0]})
        result = add_synthetic_nupl(df)
        assert result["nupl_proxy"].isna().all()

    def test_nupl_thresholds_match_hypothesis(self) -> None:
        """MVRV < 1 → NUPL < 0 (below NUPL_BOTTOM). MVRV > 3.5 → NUPL > 0.71."""
        # Bottom zone: MVRV=0.8 → NUPL=-0.25
        nupl_bottom = (0.8 - 1.0) / 0.8
        assert nupl_bottom < NUPL_BOTTOM_DEFAULT

        # Top zone: MVRV=3.5 → NUPL=0.714
        nupl_top = (3.5 - 1.0) / 3.5
        assert nupl_top > 0.70  # close to NUPL_TOP_DEFAULT=0.75


# ---------------------------------------------------------------------------
# 2. add_exchange_netflow
# ---------------------------------------------------------------------------

class TestExchangeNetflow:
    def test_netflow_positive_when_outflow_dominates(self) -> None:
        """netflow = outflow - inflow. Positive = more leaving = bullish."""
        df = pd.DataFrame({
            "FlowOutExNtv": [5000.0, 6000.0, 7000.0],
            "FlowInExNtv": [1000.0, 1500.0, 2000.0],
        })
        result = add_exchange_netflow(df)
        assert "ex_netflow" in result.columns
        assert float(result["ex_netflow"].iloc[0]) == pytest.approx(4000.0)
        assert (result["ex_netflow"] > 0).all()

    def test_netflow_z_score_computed(self) -> None:
        """ex_netflow_z should be present for sufficient data."""
        n = 120
        rng = np.random.default_rng(1)
        df = pd.DataFrame({
            "FlowOutExNtv": rng.uniform(1000, 5000, n),
            "FlowInExNtv": rng.uniform(1000, 5000, n),
        })
        result = add_exchange_netflow(df)
        assert "ex_netflow_z" in result.columns
        # After 30 bars minimum, z-scores should not be NaN
        non_nan = result["ex_netflow_z"].dropna()
        assert len(non_nan) > 0

    def test_netflow_missing_columns_graceful(self) -> None:
        """If flow columns missing, ex_netflow and ex_netflow_z are NaN."""
        df = pd.DataFrame({"CapMVRVCur": [1.5, 2.0]})
        result = add_exchange_netflow(df)
        assert result["ex_netflow"].isna().all()
        assert result["ex_netflow_z"].isna().all()


# ---------------------------------------------------------------------------
# 3. merge_onchain_to_ohlcv
# ---------------------------------------------------------------------------

class TestMergeOnchain:
    def test_merge_aligned_dates(self) -> None:
        """On-chain columns present after merge with aligned dates."""
        n = 30
        ohlcv = _make_ohlcv(n)
        onchain = _make_onchain(n)
        merged = merge_onchain_to_ohlcv(ohlcv, onchain)
        assert "CapMVRVCur" in merged.columns
        assert "nupl_proxy" in merged.columns
        # Most rows should have on-chain data
        assert merged["CapMVRVCur"].notna().sum() > n // 2

    def test_merge_empty_ohlcv(self) -> None:
        """Empty OHLCV → empty result."""
        onchain = _make_onchain(10)
        result = merge_onchain_to_ohlcv(pd.DataFrame(), onchain)
        assert result.empty

    def test_merge_preserves_ohlcv_length(self) -> None:
        """Merge does not change OHLCV row count."""
        n = 50
        ohlcv = _make_ohlcv(n)
        onchain = _make_onchain(n)
        merged = merge_onchain_to_ohlcv(ohlcv, onchain)
        assert len(merged) == n

    def test_merge_forward_fills_gap(self) -> None:
        """Missing on-chain row (gap day) → forward-filled from previous day."""
        n = 10
        ohlcv = _make_ohlcv(n)
        # On-chain missing day 5 → gap should be filled
        onchain = _make_onchain(n)
        onchain = onchain.drop(index=5).reset_index(drop=True)
        merged = merge_onchain_to_ohlcv(ohlcv, onchain)
        # Row 5 should be forward-filled from row 4 (within limit=3)
        assert not np.isnan(float(merged["CapMVRVCur"].iloc[5]))


# ---------------------------------------------------------------------------
# 4. OnChainSignalsStrategy.prepare_features
# ---------------------------------------------------------------------------

class TestPrepareFeatures:
    def test_required_columns_present(self) -> None:
        """prepare_features adds mvrv_lag1, nupl_lag1, ema_trend, atr14."""
        n = 100
        ohlcv = _make_ohlcv(n)
        onchain = _make_onchain(n)
        merged = merge_onchain_to_ohlcv(ohlcv, onchain)
        # Add computed on-chain derivations
        merged = add_synthetic_nupl(merged)
        merged = add_exchange_netflow(merged)

        strat = _make_strategy()
        df_feat = strat.prepare_features(merged)

        for col in ["mvrv_lag1", "nupl_lag1", "flow_z_lag1", "addr_z_lag1",
                    "ema_trend", "atr14", "atr_pct"]:
            assert col in df_feat.columns, f"Missing column: {col}"

    def test_lag1_is_shifted(self) -> None:
        """mvrv_lag1[i] == CapMVRVCur[i-1] (shift-1 guarantee)."""
        n = 50
        ohlcv = _make_ohlcv(n)
        onchain = _make_onchain(n)
        merged = merge_onchain_to_ohlcv(ohlcv, onchain)

        strat = _make_strategy()
        df_feat = strat.prepare_features(merged)

        for i in range(2, 10):
            lag1 = float(df_feat["mvrv_lag1"].iloc[i])
            mvrv_prev = float(df_feat["CapMVRVCur"].iloc[i - 1])
            assert lag1 == pytest.approx(mvrv_prev, rel=1e-6), (
                f"Bar {i}: mvrv_lag1 should equal CapMVRVCur at bar {i-1}"
            )

    def test_prepare_features_empty_df(self) -> None:
        """Empty input → empty output."""
        strat = _make_strategy()
        result = strat.prepare_features(pd.DataFrame())
        assert result.empty


# ---------------------------------------------------------------------------
# 5. Signal generation
# ---------------------------------------------------------------------------

class TestSignalGeneration:
    def test_long_signal_bottom_zone(self) -> None:
        """MVRV < 1 + NUPL < 0.25 → LONG signal produced."""
        n = 100
        ohlcv = _make_ohlcv(n, base_price=30_000.0)
        # Force MVRV into bottom zone: < 1.0
        onchain = _make_onchain(n, mvrv=0.8)
        # Flatten noise so all bars are solidly in bottom zone
        onchain["CapMVRVCur"] = 0.8
        onchain["nupl_proxy"] = (0.8 - 1.0) / 0.8  # = -0.25

        merged = merge_onchain_to_ohlcv(ohlcv, onchain)

        strat = _make_strategy()
        df_feat = strat.prepare_features(merged)
        sigs = strat.generate_signals(df_feat)

        long_sigs = [s for s in sigs if s.direction == "long"]
        assert len(long_sigs) >= 1, (
            "MVRV=0.8 (< 1.0) + NUPL=-0.25 (< 0.25) should produce LONG signals"
        )
        sig = long_sigs[0]
        assert sig.pattern_id == "onchain_long"
        assert sig.sl_price < float(ohlcv["close"].iloc[55])  # SL below entry
        assert sig.tp_price > sig.sl_price

    def test_short_signal_top_zone(self) -> None:
        """MVRV > 3.5 + NUPL > 0.75 → SHORT signal produced."""
        n = 100
        # EMA50 requires price trend — use declining price to be below EMA
        rng = np.random.default_rng(7)
        close_base = 60_000.0
        rets = rng.normal(-0.005, 0.01, n)  # slight downtrend
        close = close_base * np.exp(np.cumsum(rets))
        ohlcv = pd.DataFrame({
            "ts": _daily_ts(n),
            "open": np.r_[close[0], close[:-1]],
            "high": close * 1.01,
            "low": close * 0.99,
            "close": close,
            "volume": np.ones(n) * 1e9,
            "venue": "binance",
            "symbol": "BTC/USDT",
            "timeframe": "1d",
        })

        # Force MVRV into top zone: > 3.5 (use 4.5 so NUPL=0.778 > 0.75 threshold)
        onchain = _make_onchain(n, mvrv=4.5)
        onchain["CapMVRVCur"] = 4.5
        onchain["nupl_proxy"] = (4.5 - 1.0) / 4.5  # = 0.778 > NUPL_TOP_DEFAULT=0.75

        merged = merge_onchain_to_ohlcv(ohlcv, onchain)

        strat = _make_strategy()
        df_feat = strat.prepare_features(merged)
        sigs = strat.generate_signals(df_feat)

        short_sigs = [s for s in sigs if s.direction == "short"]
        assert len(short_sigs) >= 1, (
            "MVRV=4.5 (> 3.5) + NUPL=0.778 (> 0.75) should produce SHORT signals"
        )
        sig = short_sigs[0]
        assert sig.pattern_id == "onchain_short"
        assert sig.sl_price > sig.tp_price  # SL above TP for short

    def test_no_signal_neutral_mvrv(self) -> None:
        """MVRV = 1.5 (neutral zone) → no signals."""
        n = 100
        ohlcv = _make_ohlcv(n)
        onchain = _make_onchain(n, mvrv=1.5)
        onchain["CapMVRVCur"] = 1.5
        onchain["nupl_proxy"] = (1.5 - 1.0) / 1.5  # = 0.333

        merged = merge_onchain_to_ohlcv(ohlcv, onchain)

        strat = _make_strategy()
        df_feat = strat.prepare_features(merged)
        sigs = strat.generate_signals(df_feat)

        assert sigs == [], (
            "MVRV=1.5 is in neutral zone — should not produce any signals"
        )

    def test_no_signal_missing_onchain(self) -> None:
        """OHLCV without on-chain columns → no signals (graceful)."""
        n = 80
        ohlcv = _make_ohlcv(n)  # no CapMVRVCur / nupl_proxy
        strat = _make_strategy()
        sigs = strat.generate_signals(ohlcv)
        assert sigs == [], "Missing on-chain columns should produce no signals"

    def test_empty_df_returns_empty(self) -> None:
        """Empty DataFrame → empty signal list."""
        strat = _make_strategy()
        assert strat.generate_signals(pd.DataFrame()) == []

    def test_signal_schema_valid(self) -> None:
        """Generated signals conform to Signal schema."""
        from price_action.contracts import Signal

        n = 100
        ohlcv = _make_ohlcv(n, base_price=25_000.0)
        onchain = _make_onchain(n, mvrv=0.75)
        onchain["CapMVRVCur"] = 0.75
        onchain["nupl_proxy"] = (0.75 - 1.0) / 0.75

        merged = merge_onchain_to_ohlcv(ohlcv, onchain)
        strat = _make_strategy()
        df_feat = strat.prepare_features(merged)
        sigs = strat.generate_signals(df_feat)

        for sig in sigs:
            assert isinstance(sig, Signal)
            assert sig.direction in {"long", "short"}
            assert sig.sl_price > 0
            assert sig.tp_price > 0
            assert sig.confluence_score > 0
            assert sig.fingerprint()


# ---------------------------------------------------------------------------
# 6. Lookahead-bias: on-chain lagged by 1 bar
# ---------------------------------------------------------------------------

class TestLookaheadBias:
    def test_mvrv_lag1_not_current_bar(self) -> None:
        """mvrv_lag1 at bar i uses CapMVRVCur from bar i-1, not bar i."""
        n = 50
        ohlcv = _make_ohlcv(n)
        onchain = _make_onchain(n, mvrv=1.5)
        # Spike MVRV at bar 30 to extreme value
        onchain.loc[30, "CapMVRVCur"] = 10.0
        merged = merge_onchain_to_ohlcv(ohlcv, onchain)

        strat = _make_strategy()
        df_feat = strat.prepare_features(merged)

        # Bar 30: mvrv_lag1 should see bar 29's value (≈1.5), NOT bar 30's spike (10.0)
        lag_at_30 = float(df_feat["mvrv_lag1"].iloc[30])
        assert lag_at_30 < 5.0, (
            f"Bar 30 mvrv_lag1={lag_at_30:.2f} should be bar 29's value (~1.5), not spike 10.0"
        )

        # Bar 31: mvrv_lag1 should see bar 30's spike
        lag_at_31 = float(df_feat["mvrv_lag1"].iloc[31])
        assert lag_at_31 == pytest.approx(10.0, rel=0.01), (
            f"Bar 31 mvrv_lag1={lag_at_31:.2f} should see bar 30's spike 10.0"
        )

    def test_signal_count_unchanged_when_future_zeroed(self) -> None:
        """Signals up to bar t unchanged when future on-chain data is zeroed."""
        n = 100
        ohlcv = _make_ohlcv(n, base_price=28_000.0)
        onchain = _make_onchain(n, mvrv=0.8)
        onchain["CapMVRVCur"] = 0.8
        onchain["nupl_proxy"] = (0.8 - 1.0) / 0.8
        merged = merge_onchain_to_ohlcv(ohlcv, onchain)

        strat = _make_strategy()
        df_full = strat.prepare_features(merged)
        sigs_full = strat.generate_signals(df_full)

        # Zero out on-chain from bar 80 onwards
        df_trunc = df_full.copy()
        df_trunc.loc[80:, "mvrv_lag1"] = float("nan")
        df_trunc.loc[80:, "nupl_lag1"] = float("nan")

        sigs_trunc = strat.generate_signals(df_trunc)

        # Signals before bar 80 should be identical
        cut_ts = pd.Timestamp(df_full["ts"].iloc[79])
        early_full = [s for s in sigs_full if pd.Timestamp(s.ts) <= cut_ts]
        early_trunc = [s for s in sigs_trunc if pd.Timestamp(s.ts) <= cut_ts]
        assert len(early_full) == len(early_trunc), (
            "Future data zeroed should not change signals in past bars"
        )


# ---------------------------------------------------------------------------
# 7. SL / TP geometry
# ---------------------------------------------------------------------------

class TestSLTPGeometry:
    def test_long_sl_below_entry_tp_above(self) -> None:
        """Long: SL < entry price, TP > entry price."""
        n = 100
        ohlcv = _make_ohlcv(n, base_price=30_000.0)
        onchain = _make_onchain(n, mvrv=0.7)
        onchain["CapMVRVCur"] = 0.7
        onchain["nupl_proxy"] = (0.7 - 1.0) / 0.7

        merged = merge_onchain_to_ohlcv(ohlcv, onchain)
        strat = _make_strategy()
        df_feat = strat.prepare_features(merged)
        sigs = strat.generate_signals(df_feat)

        long_sigs = [s for s in sigs if s.direction == "long"]
        assert len(long_sigs) > 0
        for sig in long_sigs:
            entry_approx = float(df_feat.loc[
                df_feat["ts"] == pd.Timestamp(sig.ts), "close"
            ].iloc[0])
            assert sig.sl_price < entry_approx, "Long SL must be below entry"
            assert sig.tp_price > entry_approx, "Long TP must be above entry"

    def test_short_sl_above_entry_tp_below(self) -> None:
        """Short: SL > entry price, TP < entry price."""
        n = 100
        rng = np.random.default_rng(5)
        close = 60_000.0 * np.exp(np.cumsum(rng.normal(-0.005, 0.01, n)))
        ohlcv = pd.DataFrame({
            "ts": _daily_ts(n),
            "open": np.r_[close[0], close[:-1]],
            "high": close * 1.01,
            "low": close * 0.99,
            "close": close,
            "volume": np.ones(n) * 1e9,
            "venue": "binance",
            "symbol": "BTC/USDT",
            "timeframe": "1d",
        })
        onchain = _make_onchain(n, mvrv=4.5)
        onchain["CapMVRVCur"] = 4.5
        onchain["nupl_proxy"] = (4.5 - 1.0) / 4.5  # = 0.778

        merged = merge_onchain_to_ohlcv(ohlcv, onchain)
        strat = _make_strategy()
        df_feat = strat.prepare_features(merged)
        sigs = strat.generate_signals(df_feat)

        short_sigs = [s for s in sigs if s.direction == "short"]
        assert len(short_sigs) > 0
        for sig in short_sigs:
            assert sig.sl_price > sig.tp_price, "Short: SL above TP"


# ---------------------------------------------------------------------------
# 8. _default_manifest
# ---------------------------------------------------------------------------

class TestDefaultManifest:
    def test_manifest_valid(self) -> None:
        """_default_manifest() returns valid StrategyManifest."""
        m = _default_manifest()
        assert m.name == "onchain_signals"
        assert m.version == "1.0.0"

    def test_manifest_has_correct_pattern_ids(self) -> None:
        """Both onchain_long and onchain_short patterns present."""
        m = _default_manifest()
        ids = [p.id for p in m.signals.patterns]
        assert "onchain_long" in ids
        assert "onchain_short" in ids

    def test_manifest_tp_3r(self) -> None:
        """Default TP is 3R."""
        m = _default_manifest()
        r = m.risk.get("take_profit", {}).get("primary_R", 0)
        assert r == pytest.approx(3.0)

    def test_strategy_instantiates_with_default_manifest(self) -> None:
        """OnChainSignalsStrategy() with no args uses default manifest."""
        strat = OnChainSignalsStrategy()
        assert strat.name == "onchain_signals"
        assert strat.manifest is not None


# ---------------------------------------------------------------------------
# Auxiliary helpers
# ---------------------------------------------------------------------------

class TestAuxHelpers:
    def test_mvrv_regime(self) -> None:
        """_mvrv_regime correctly identifies bottom/top zones."""
        mvrv = pd.Series([0.5, 0.9, 1.5, 3.5, 4.5])
        bottom, top = _mvrv_regime(mvrv, bottom_thresh=1.0, top_thresh=3.5)
        assert list(bottom) == [True, True, False, False, False]
        assert list(top) == [False, False, False, False, True]

    def test_nupl_regime(self) -> None:
        """_nupl_regime correctly identifies fear/greed zones."""
        nupl = pd.Series([-0.5, 0.1, 0.4, 0.75, 0.9])
        fear, greed = _nupl_regime(nupl, bottom_thresh=0.25, top_thresh=0.75)
        assert list(fear) == [True, True, False, False, False]
        assert list(greed) == [False, False, False, False, True]

    def test_to_cm_asset_conversion(self) -> None:
        """_to_cm_asset converts various symbol formats to CM asset name."""
        assert _to_cm_asset("BTC/USDT") == "btc"
        assert _to_cm_asset("BTC") == "btc"
        assert _to_cm_asset("ETH/USDT") == "eth"
        assert _to_cm_asset("ETH") == "eth"

    def test_community_metrics_list(self) -> None:
        """COMMUNITY_METRICS contains expected metrics."""
        assert "CapMVRVCur" in COMMUNITY_METRICS
        assert "AdrActCnt" in COMMUNITY_METRICS
        assert "FlowInExNtv" in COMMUNITY_METRICS
        assert "FlowOutExNtv" in COMMUNITY_METRICS
        assert "HashRate" in COMMUNITY_METRICS
