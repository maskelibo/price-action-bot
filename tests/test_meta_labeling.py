"""Unit tests — meta_labeling module.

Test coverage:
  1. triple_barrier_labels: sane labels, +1/-1/0 range, no future-bar in label decision
  2. engineer_features: no lookahead, expected columns, numerical validity
  3. train_rf: fits without error, returns metrics, model serializable
  4. predict_filter: returns boolean mask, respects threshold
  5. sample weights: uniqueness weight properties
"""
from __future__ import annotations

import io
import os
import pickle
import tempfile
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
import pytest

# ---------------------------------------------------------------------------
# Skip if scikit-learn not available
# ---------------------------------------------------------------------------
sklearn = pytest.importorskip("sklearn", reason="scikit-learn required for meta_labeling tests")

from price_action.ml.meta_labeling import (
    _compute_sample_weights,
    _purged_kfold_splits,
    engineer_features,
    predict_filter,
    train_rf,
    triple_barrier_labels,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_ohlcv(n: int = 200, seed: int = 42) -> pd.DataFrame:
    """Synthetic OHLCV DataFrame with pre-computed ATR and EMAs."""
    rng = np.random.default_rng(seed)
    drift = 0.002
    rets = rng.normal(drift, 0.015, n)
    close = 100.0 * np.exp(np.cumsum(rets))
    open_ = np.r_[close[0], close[:-1]] * rng.uniform(0.995, 1.005, n)
    high = np.maximum(open_, close) * rng.uniform(1.001, 1.015, n)
    low = np.minimum(open_, close) * rng.uniform(0.985, 0.999, n)
    high = np.maximum.reduce([high, open_, close])
    low = np.minimum.reduce([low, open_, close])
    volume = rng.uniform(1e6, 5e6, n)
    start = datetime(2022, 1, 1, tzinfo=timezone.utc)
    ts = [start + timedelta(days=i) for i in range(n)]

    df = pd.DataFrame({
        "ts": ts,
        "open": open_,
        "high": high,
        "low": low,
        "close": close,
        "volume": volume,
        "venue": "binance",
        "symbol": "BTC/USDT",
        "timeframe": "1d",
    })
    # Pre-compute ATR
    hi, lo, pc = df["high"], df["low"], df["close"].shift(1)
    tr = pd.concat([(hi - lo).abs(), (hi - pc).abs(), (lo - pc).abs()], axis=1).max(axis=1)
    df["atr14"] = tr.rolling(14, min_periods=1).mean()
    df["ema20"] = df["close"].ewm(span=20, adjust=False).mean()
    df["ema200"] = df["close"].ewm(span=200, adjust=False).mean()
    return df


def _make_signals(df: pd.DataFrame, n_sigs: int = 30, seed: int = 7) -> list[dict]:
    """Generate synthetic signal dicts at random bars (past-safe)."""
    rng = np.random.default_rng(seed)
    # Use bars 50..n-20 to leave room for max_holding
    valid_rows = df.iloc[50:-20]
    chosen = valid_rows.sample(n=min(n_sigs, len(valid_rows)), random_state=int(seed))
    signals = []
    for _, row in chosen.iterrows():
        c = float(row["close"])
        atr = float(row["atr14"])
        direction = rng.choice(["long", "short"])
        if direction == "long":
            sl = c - 1.0 * atr
            tp = c + 2.0 * atr
        else:
            sl = c + 1.0 * atr
            tp = c - 2.0 * atr
        signals.append({
            "ts": row["ts"],
            "direction": direction,
            "sl_price": sl,
            "tp_price": tp,
            "confluence_score": float(rng.uniform(1.5, 2.5)),
            "metadata": {"near_sr": bool(rng.integers(0, 2))},
        })
    return signals


# ===========================================================================
# 1. Triple-barrier label tests
# ===========================================================================

class TestTripleBarrierLabels:
    def test_returns_dataframe_with_correct_columns(self):
        df = _make_ohlcv(200)
        signals = _make_signals(df, n_sigs=20)
        labels = triple_barrier_labels(df, signals, max_holding=20)
        assert isinstance(labels, pd.DataFrame)
        for col in ["signal_ts", "direction", "label", "t0", "t1", "holding_bars", "pnl_pct"]:
            assert col in labels.columns, f"Missing column: {col}"

    def test_labels_in_valid_range(self):
        df = _make_ohlcv(200)
        signals = _make_signals(df, n_sigs=30)
        labels = triple_barrier_labels(df, signals, max_holding=15)
        assert not labels.empty, "Should produce at least some labels"
        assert labels["label"].isin([-1, 0, 1]).all(), "Labels must be -1, 0 or +1"

    def test_holding_bars_bounded_by_max_holding(self):
        df = _make_ohlcv(200)
        signals = _make_signals(df, n_sigs=25)
        max_h = 10
        labels = triple_barrier_labels(df, signals, max_holding=max_h)
        assert (labels["holding_bars"] <= max_h).all(), \
            "holding_bars must never exceed max_holding"

    def test_t0_less_than_t1(self):
        df = _make_ohlcv(200)
        signals = _make_signals(df, n_sigs=20)
        labels = triple_barrier_labels(df, signals, max_holding=20)
        assert (labels["t1"] >= labels["t0"]).all(), "t1 must be >= t0"

    def test_no_future_bar_used_in_label_for_signal_bar(self):
        """The label barrier scan starts at bar t+1 (entry), not at t."""
        df = _make_ohlcv(200)
        signals = _make_signals(df, n_sigs=10)
        labels_full = triple_barrier_labels(df, signals, max_holding=20)

        # Truncate df to bar t (signal bar) — forward bars removed
        # Labels should NOT be computed (not enough forward bars)
        first_sig = signals[0]
        sig_ts = pd.Timestamp(first_sig["ts"])
        if sig_ts.tzinfo is None:
            sig_ts = sig_ts.tz_localize("UTC")
        else:
            sig_ts = sig_ts.tz_convert("UTC")
        df_ts = df.copy()
        df_ts["ts"] = pd.to_datetime(df_ts["ts"], utc=True)
        sig_idx = df_ts[df_ts["ts"] == sig_ts].index
        if len(sig_idx) == 0:
            pytest.skip("Signal not found in df")
        bar_i = int(sig_idx[0])
        # Truncate to just signal bar (no forward bars)
        df_trunc = df.iloc[:bar_i + 1].copy()
        labels_trunc = triple_barrier_labels(df_trunc, [first_sig], max_holding=20)
        # With no forward bars, signal should be skipped (i+1 >= len)
        assert labels_trunc.empty, \
            "Signal with no forward bars should produce no labels (no lookahead)"

    def test_empty_signals_returns_empty_df(self):
        df = _make_ohlcv(100)
        labels = triple_barrier_labels(df, [])
        assert isinstance(labels, pd.DataFrame)
        assert labels.empty

    def test_tp_label_when_strong_move(self):
        """Force a TP hit: set high > tp_price on bar t+1."""
        df = _make_ohlcv(100, seed=1)
        bar_idx = 50
        sig_ts = df.iloc[bar_idx]["ts"]
        c = float(df.iloc[bar_idx]["close"])
        entry_open = float(df.iloc[bar_idx + 1]["open"])

        # Set TP just above entry; set bar t+1 high far above TP
        tp = entry_open * 1.001
        sl = entry_open * 0.95  # SL far below — won't hit

        df_mod = df.copy()
        df_mod.loc[bar_idx + 1, "high"] = entry_open * 1.05  # triggers TP
        df_mod.loc[bar_idx + 1, "low"] = entry_open * 0.999  # doesn't trigger SL

        sig = {
            "ts": sig_ts,
            "direction": "long",
            "sl_price": sl,
            "tp_price": tp,
        }
        labels = triple_barrier_labels(df_mod, [sig], max_holding=20)
        assert not labels.empty
        assert int(labels.iloc[0]["label"]) == 1, "Should be TP hit (+1)"

    def test_sl_label_when_sharp_drop(self):
        """Force an SL hit: set low < sl_price on bar t+1."""
        df = _make_ohlcv(100, seed=2)
        bar_idx = 50
        sig_ts = df.iloc[bar_idx]["ts"]
        entry_open = float(df.iloc[bar_idx + 1]["open"])

        tp = entry_open * 1.5   # TP far above — won't hit
        sl = entry_open * 0.999  # SL just below entry

        df_mod = df.copy()
        df_mod.loc[bar_idx + 1, "low"] = entry_open * 0.90  # triggers SL
        df_mod.loc[bar_idx + 1, "high"] = entry_open * 1.001  # doesn't trigger TP

        sig = {
            "ts": sig_ts,
            "direction": "long",
            "sl_price": sl,
            "tp_price": tp,
        }
        labels = triple_barrier_labels(df_mod, [sig], max_holding=20)
        assert not labels.empty
        assert int(labels.iloc[0]["label"]) == -1, "Should be SL hit (-1)"


# ===========================================================================
# 2. Feature engineering tests
# ===========================================================================

class TestEngineerFeatures:
    def test_returns_dataframe_with_expected_columns(self):
        df = _make_ohlcv(200)
        signals = _make_signals(df, n_sigs=20)
        feats = engineer_features(df, signals)
        assert not feats.empty
        expected = [
            "atr_pct", "kaufman_er", "body_ratio",
            "close_to_ema20_pct", "close_above_200ema", "volume_z",
            "rolling_5d_return", "rolling_20d_return", "rolling_5d_vol",
            "confluence_score", "near_sr", "swing_distance_atr",
            "rolling_60d_sharpe",
        ]
        for col in expected:
            assert col in feats.columns, f"Missing feature: {col}"

    def test_no_inf_or_nan_after_fill(self):
        df = _make_ohlcv(200)
        signals = _make_signals(df, n_sigs=25)
        feats = engineer_features(df, signals)
        num_cols = [c for c in feats.columns if c != "direction"]
        assert not feats[num_cols].isnull().any().any(), "No NaN after feature fill"
        assert not np.isinf(feats[num_cols].values).any(), "No Inf in features"

    def test_no_lookahead_in_features(self):
        """Features at bar t must not depend on bars after t.

        Method: compute features normally, then zero-out all bars after signal bar
        and recompute — features should be identical for the signal bar.
        """
        df = _make_ohlcv(150)
        signals = _make_signals(df, n_sigs=5, seed=11)

        feats_full = engineer_features(df, signals)
        if feats_full.empty:
            pytest.skip("No features produced")

        # For first signal, check that truncating future data gives same result
        first_sig = signals[0]
        sig_ts = pd.Timestamp(first_sig["ts"])
        if sig_ts.tzinfo is None:
            sig_ts = sig_ts.tz_localize("UTC")
        else:
            sig_ts = sig_ts.tz_convert("UTC")

        df_ts = df.copy()
        df_ts["ts"] = pd.to_datetime(df_ts["ts"], utc=True)
        sig_rows = df_ts[df_ts["ts"] == sig_ts]
        if sig_rows.empty:
            pytest.skip("Signal bar not in df")

        bar_i = int(sig_rows.index[0])
        # Truncate df to signal bar (inclusive) — remove all future bars
        df_trunc = df.iloc[:bar_i + 1].copy()
        feats_trunc = engineer_features(df_trunc, [first_sig])

        if feats_trunc.empty or feats_full.empty:
            pytest.skip("Empty features")

        # Both should have a row for this signal
        if sig_ts not in feats_full.index or sig_ts not in feats_trunc.index:
            pytest.skip("Signal timestamp not in feature index")

        row_full = feats_full.loc[sig_ts]
        row_trunc = feats_trunc.loc[sig_ts]

        num_cols = [c for c in row_full.index if c not in ("direction",)]
        for col in num_cols:
            v_full = float(row_full[col])
            v_trunc = float(row_trunc[col])
            assert abs(v_full - v_trunc) < 1e-6, \
                f"Feature '{col}' differs with/without future bars: {v_full} vs {v_trunc}"

    def test_body_ratio_in_0_1(self):
        df = _make_ohlcv(200)
        signals = _make_signals(df, n_sigs=20)
        feats = engineer_features(df, signals)
        assert (feats["body_ratio"] >= 0.0).all()
        assert (feats["body_ratio"] <= 1.0).all()

    def test_close_above_200ema_binary(self):
        df = _make_ohlcv(200)
        signals = _make_signals(df, n_sigs=15)
        feats = engineer_features(df, signals)
        assert feats["close_above_200ema"].isin([0.0, 1.0]).all()

    def test_near_sr_binary(self):
        df = _make_ohlcv(200)
        signals = _make_signals(df, n_sigs=15)
        feats = engineer_features(df, signals)
        assert feats["near_sr"].isin([0.0, 1.0]).all()

    def test_empty_signals_returns_empty(self):
        df = _make_ohlcv(100)
        feats = engineer_features(df, [])
        assert isinstance(feats, pd.DataFrame)
        assert feats.empty


# ===========================================================================
# 3. Sample weights tests
# ===========================================================================

class TestSampleWeights:
    def test_weights_sum_to_n(self):
        """Total weight should be normalized to n_samples."""
        labels_df = pd.DataFrame({
            "signal_ts": pd.date_range("2022-01-01", periods=10, freq="D", tz="UTC"),
            "t0": range(0, 20, 2),
            "t1": range(5, 25, 2),
            "label": [1, -1, 1, 0, 1, -1, 0, 1, -1, 1],
        })
        w = _compute_sample_weights(labels_df)
        assert len(w) == 10
        # Sum should be approximately n (normalized)
        assert abs(w.sum() - 10.0) < 1.0, f"Weights sum={w.sum()}, expected ~10"

    def test_weights_non_negative(self):
        labels_df = pd.DataFrame({
            "signal_ts": pd.date_range("2022-01-01", periods=5, freq="D", tz="UTC"),
            "t0": [0, 10, 20, 30, 40],
            "t1": [5, 15, 25, 35, 45],
            "label": [1, -1, 1, 0, -1],
        })
        w = _compute_sample_weights(labels_df)
        assert (w >= 0).all(), "All weights must be non-negative"

    def test_non_overlapping_samples_have_equal_weight(self):
        """Non-overlapping samples should all have equal uniqueness (=1.0 each)."""
        labels_df = pd.DataFrame({
            "signal_ts": pd.date_range("2022-01-01", periods=5, freq="D", tz="UTC"),
            "t0": [0, 10, 20, 30, 40],   # no overlap between any pair
            "t1": [5, 15, 25, 35, 45],
            "label": [1, -1, 1, 0, -1],
        })
        w = _compute_sample_weights(labels_df)
        # All non-overlapping → uniqueness = 1.0 for all → after norm all equal
        std_w = float(np.std(w))
        assert std_w < 0.01, f"Non-overlapping samples should have equal weights, std={std_w}"


# ===========================================================================
# 4. Purged k-fold CV tests
# ===========================================================================

class TestPurgedKFold:
    def test_produces_n_folds(self):
        labels_df = pd.DataFrame({
            "t0": range(0, 50, 2),
            "t1": range(5, 55, 2),
            "label": [1] * 25,
        })
        splits = _purged_kfold_splits(labels_df, n_folds=5, embargo_bars=2)
        assert len(splits) > 0, "Should produce at least 1 split"
        assert len(splits) <= 5

    def test_no_train_test_overlap_in_bar_time(self):
        """Train samples should not overlap test bar range after purging."""
        labels_df = pd.DataFrame({
            "t0": range(0, 100, 2),
            "t1": range(5, 105, 2),
            "label": [1] * 50,
        })
        splits = _purged_kfold_splits(labels_df, n_folds=5, embargo_bars=3)
        t0s = labels_df["t0"].values
        t1s = labels_df["t1"].values

        for tr_idx, te_idx in splits:
            te_t0_min = int(t0s[te_idx].min())
            te_t1_max = int(t1s[te_idx].max())
            for tr_i in tr_idx:
                si_t0 = int(t0s[tr_i])
                si_t1 = int(t1s[tr_i])
                overlaps = si_t1 >= te_t0_min and si_t0 <= te_t1_max
                assert not overlaps, (
                    f"Train sample [{si_t0},{si_t1}] overlaps test window "
                    f"[{te_t0_min},{te_t1_max}] — purging failed"
                )

    def test_test_indices_disjoint_across_folds(self):
        labels_df = pd.DataFrame({
            "t0": range(0, 60),
            "t1": range(3, 63),
            "label": [1, -1] * 30,
        })
        splits = _purged_kfold_splits(labels_df, n_folds=5, embargo_bars=2)
        seen: set[int] = set()
        for _, te_idx in splits:
            te_set = set(te_idx.tolist())
            # Each test fold should be unique (no index used twice as test)
            overlap = seen & te_set
            assert len(overlap) == 0, f"Test indices used in multiple folds: {overlap}"
            seen.update(te_set)


# ===========================================================================
# 5. Train RF tests
# ===========================================================================

class TestTrainRF:
    def _make_training_data(self, n: int = 80, seed: int = 99) -> tuple[pd.DataFrame, pd.Series, pd.DataFrame]:
        df = _make_ohlcv(n + 50, seed=seed)
        signals = _make_signals(df, n_sigs=n, seed=seed)
        feats = engineer_features(df, signals)
        labels = triple_barrier_labels(df, signals, max_holding=10)
        if feats.empty or labels.empty:
            return pd.DataFrame(), pd.Series(dtype=int), pd.DataFrame()
        # Align on signal_ts
        labels["signal_ts"] = pd.to_datetime(labels["signal_ts"], utc=True)
        labels_indexed = labels.set_index("signal_ts")
        common = feats.index.intersection(labels_indexed.index)
        feats_a = feats.loc[common]
        labels_a = labels_indexed.loc[common]
        # Binary label: 1 = TP (+1), 0 = SL or timeout
        y = (labels_a["label"] == 1).astype(int)
        return feats_a, y, labels_a.reset_index()

    def test_train_returns_model_and_metrics(self):
        feats, y, ldf = self._make_training_data(80)
        if len(feats) < 10:
            pytest.skip("Not enough samples")
        model, metrics = train_rf(feats, y, labels_df=ldf, cv=3)
        assert model is not None
        assert "train_accuracy" in metrics
        assert "cv_mean_accuracy" in metrics
        assert 0.0 <= metrics["train_accuracy"] <= 1.0

    def test_train_accuracy_sane(self):
        """Train accuracy should be above chance (>0.4) for RF on any data."""
        feats, y, ldf = self._make_training_data(80)
        if len(feats) < 10:
            pytest.skip("Not enough samples")
        model, metrics = train_rf(feats, y, labels_df=ldf, cv=3, n_estimators=50)
        # RF will overfit to train — train accuracy should be high
        assert metrics["train_accuracy"] > 0.4, \
            f"Train accuracy too low: {metrics['train_accuracy']}"

    def test_feature_importance_all_features_present(self):
        feats, y, ldf = self._make_training_data(80)
        if len(feats) < 10:
            pytest.skip("Not enough samples")
        model, metrics = train_rf(feats, y, labels_df=ldf, cv=3, n_estimators=50)
        feat_cols = [c for c in feats.columns if c != "direction"]
        importance = metrics.get("feature_importance", {})
        for col in feat_cols:
            assert col in importance, f"Missing feature importance: {col}"

    def test_metrics_label_balance_correct(self):
        feats, y, ldf = self._make_training_data(80)
        if len(feats) < 10:
            pytest.skip("Not enough samples")
        _, metrics = train_rf(feats, y, labels_df=ldf, cv=3, n_estimators=50)
        reported_balance = metrics["label_balance"]
        actual_balance = float(y.mean())
        assert abs(reported_balance - actual_balance) < 0.01


# ===========================================================================
# 6. Predict filter tests
# ===========================================================================

class TestPredictFilter:
    def _train_model(self, n: int = 80):
        df = _make_ohlcv(n + 50, seed=55)
        signals = _make_signals(df, n_sigs=n, seed=55)
        feats = engineer_features(df, signals)
        labels = triple_barrier_labels(df, signals, max_holding=10)
        if feats.empty or labels.empty:
            return None, None, None
        labels["signal_ts"] = pd.to_datetime(labels["signal_ts"], utc=True)
        li = labels.set_index("signal_ts")
        common = feats.index.intersection(li.index)
        feats_a = feats.loc[common]
        y = (li.loc[common, "label"] == 1).astype(int)
        ldf = li.loc[common].reset_index()
        model, metrics = train_rf(feats_a, y, labels_df=ldf, cv=3, n_estimators=50)
        feat_names = metrics.get("feature_names", [])
        return model, feats_a, feat_names

    def test_predict_filter_returns_bool_series(self):
        model, feats, feat_names = self._train_model()
        if model is None:
            pytest.skip("Not enough data")
        mask = predict_filter(model, feats, threshold=0.55, feature_names=feat_names)
        assert isinstance(mask, pd.Series)
        assert mask.dtype == bool

    def test_predict_filter_index_matches_input(self):
        model, feats, feat_names = self._train_model()
        if model is None:
            pytest.skip("Not enough data")
        mask = predict_filter(model, feats, threshold=0.55, feature_names=feat_names)
        assert mask.index.equals(feats.index), "Output index must match input index"

    def test_higher_threshold_fewer_trades(self):
        model, feats, feat_names = self._train_model()
        if model is None:
            pytest.skip("Not enough data")
        mask_low = predict_filter(model, feats, threshold=0.3, feature_names=feat_names)
        mask_high = predict_filter(model, feats, threshold=0.8, feature_names=feat_names)
        assert mask_high.sum() <= mask_low.sum(), \
            "Higher threshold should take fewer or equal trades"

    def test_threshold_0_takes_all(self):
        model, feats, feat_names = self._train_model()
        if model is None:
            pytest.skip("Not enough data")
        mask = predict_filter(model, feats, threshold=0.0, feature_names=feat_names)
        assert mask.all(), "Threshold=0.0 should take all trades"

    def test_threshold_1_takes_none(self):
        model, feats, feat_names = self._train_model()
        if model is None:
            pytest.skip("Not enough data")
        mask = predict_filter(model, feats, threshold=1.01, feature_names=feat_names)
        assert not mask.any(), "Threshold>1.0 should take no trades"


# ===========================================================================
# 7. Model serialization tests
# ===========================================================================

class TestModelSerializable:
    def test_model_pickle_roundtrip(self):
        """Fitted RF model must survive pickle round-trip (joblib compatibility)."""
        df = _make_ohlcv(120, seed=33)
        signals = _make_signals(df, n_sigs=50, seed=33)
        feats = engineer_features(df, signals)
        labels = triple_barrier_labels(df, signals, max_holding=10)
        if feats.empty or labels.empty:
            pytest.skip("Not enough data for serialization test")
        labels["signal_ts"] = pd.to_datetime(labels["signal_ts"], utc=True)
        li = labels.set_index("signal_ts")
        common = feats.index.intersection(li.index)
        if len(common) < 10:
            pytest.skip("Not enough common samples")
        feats_a = feats.loc[common]
        y = (li.loc[common, "label"] == 1).astype(int)
        ldf = li.loc[common].reset_index()
        model, metrics = train_rf(feats_a, y, labels_df=ldf, cv=3, n_estimators=30)

        # Pickle round-trip
        buf = io.BytesIO()
        pickle.dump(model, buf)
        buf.seek(0)
        model2 = pickle.load(buf)

        feat_names = metrics.get("feature_names", [])
        mask1 = predict_filter(model, feats_a, threshold=0.5, feature_names=feat_names)
        mask2 = predict_filter(model2, feats_a, threshold=0.5, feature_names=feat_names)
        assert (mask1 == mask2).all(), "Pickled model must produce identical predictions"

    def test_model_save_load_joblib(self):
        """save_model / load_model round-trip."""
        from price_action.ml.meta_labeling import load_model, save_model

        df = _make_ohlcv(120, seed=44)
        signals = _make_signals(df, n_sigs=40, seed=44)
        feats = engineer_features(df, signals)
        labels = triple_barrier_labels(df, signals, max_holding=10)
        if feats.empty or labels.empty:
            pytest.skip("Not enough data for save/load test")
        labels["signal_ts"] = pd.to_datetime(labels["signal_ts"], utc=True)
        li = labels.set_index("signal_ts")
        common = feats.index.intersection(li.index)
        if len(common) < 10:
            pytest.skip("Not enough common samples")
        feats_a = feats.loc[common]
        y = (li.loc[common, "label"] == 1).astype(int)
        ldf = li.loc[common].reset_index()
        model, metrics = train_rf(feats_a, y, labels_df=ldf, cv=3, n_estimators=30)

        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "model.joblib")
            save_model(model, metrics, path)
            model2, metrics2 = load_model(path)

        feat_names = metrics.get("feature_names", [])
        mask1 = predict_filter(model, feats_a, threshold=0.5, feature_names=feat_names)
        mask2 = predict_filter(model2, feats_a, threshold=0.5, feature_names=feat_names)
        assert (mask1 == mask2).all(), "Loaded model must produce identical predictions"
        assert abs(metrics2["train_accuracy"] - metrics["train_accuracy"]) < 1e-6
