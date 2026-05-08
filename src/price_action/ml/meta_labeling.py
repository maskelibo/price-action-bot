"""López de Prado meta-labeling for engulfing_continuation signals.

Pipeline:
  1. triple_barrier_labels  — generate +1/-1/0 labels from OHLCV + signal list
  2. engineer_features      — extract lookahead-free features per signal bar
  3. train_rf               — Random Forest with purged k-fold CV (López §5.2)
  4. predict_filter         — apply trained model: trade if P(win) >= threshold

Design invariants:
  - NO future data at signal bar t.  Features use only [0..t] rows.
  - Labels use [t+1 .. t+max_holding] rows (forward-looking, as intended).
  - Purged CV ensures test-fold label intervals never overlap train set.
  - sample_weight = uniqueness (López §3.5): each sample weighted by the
    fraction of its label window that does not overlap other samples.
"""
from __future__ import annotations

import warnings
from typing import Any

import numpy as np
import pandas as pd

try:
    from sklearn.ensemble import RandomForestClassifier
    from sklearn.metrics import accuracy_score, roc_auc_score
    _SKLEARN_OK = True
except ImportError:  # pragma: no cover
    _SKLEARN_OK = False
    RandomForestClassifier = None  # type: ignore[misc,assignment]

from price_action.logging_config import logger


# =====================================================================
# 1. Triple-barrier labeling
# =====================================================================

def triple_barrier_labels(
    df: pd.DataFrame,
    signals: list[dict] | pd.DataFrame,
    *,
    atr_mult_tp: float = 2.0,
    atr_mult_sl: float = 1.0,
    max_holding: int = 20,
    atr_col: str = "atr14",
) -> pd.DataFrame:
    """Generate +1/-1/0 labels via López triple-barrier method.

    Parameters
    ----------
    df       : OHLCV DataFrame with columns [ts, open, high, low, close, atr14].
               Must be sorted by ts ascending.
    signals  : list of dicts (or DataFrame) with keys:
               ts (entry bar timestamp), direction ('long'|'short'),
               sl_price, tp_price.
               The bar at ts is the SIGNAL bar; entry happens at bar t+1 open.
    atr_mult_tp, atr_mult_sl : ATR multipliers for barrier widths.
               Ignored if sl_price/tp_price already set on signal.
    max_holding : vertical barrier (max bars to hold).
    atr_col  : column name for ATR in df.

    Returns
    -------
    DataFrame with columns:
        signal_ts, direction, entry_bar_idx, t0, t1,
        label (+1 = TP hit, -1 = SL hit, 0 = timeout/neutral),
        holding_bars, pnl_pct
    """
    if isinstance(signals, pd.DataFrame):
        sig_records = signals.to_dict("records")
    else:
        sig_records = list(signals)

    df = df.copy().reset_index(drop=True)
    df["ts"] = pd.to_datetime(df["ts"], utc=True)

    # Fast ts -> bar index lookup
    ts_to_idx: dict[pd.Timestamp, int] = {
        pd.Timestamp(t): i for i, t in enumerate(df["ts"])
    }

    rows: list[dict[str, Any]] = []
    for sig in sig_records:
        sig_ts = pd.Timestamp(sig["ts"])
        if sig_ts.tzinfo is None:
            sig_ts = sig_ts.tz_localize("UTC")
        else:
            sig_ts = sig_ts.tz_convert("UTC")

        i = ts_to_idx.get(sig_ts)
        if i is None or i + 1 >= len(df):
            continue

        entry_i = i + 1  # entry at next-bar open
        entry_bar = df.iloc[entry_i]
        entry_price = float(entry_bar["open"])
        direction = str(sig.get("direction", "long"))

        # Determine barriers from signal or ATR multiples
        atr = float(df.iloc[i].get(atr_col, 0.0) or 0.0)
        if atr <= 0:
            atr = float(entry_price * 0.01)  # fallback 1%

        sl_price = float(sig.get("sl_price") or (
            entry_price - atr_mult_sl * atr if direction == "long"
            else entry_price + atr_mult_sl * atr
        ))
        tp_price = float(sig.get("tp_price") or (
            entry_price + atr_mult_tp * atr if direction == "long"
            else entry_price - atr_mult_tp * atr
        ))

        # Ensure barriers are directionally correct
        if direction == "long":
            sl_price = min(sl_price, entry_price * 0.999)
            tp_price = max(tp_price, entry_price * 1.001)
        else:
            sl_price = max(sl_price, entry_price * 1.001)
            tp_price = min(tp_price, entry_price * 0.999)

        label = 0
        exit_i = min(entry_i + max_holding, len(df) - 1)
        holding = 0

        for j in range(entry_i, min(entry_i + max_holding + 1, len(df))):
            bar = df.iloc[j]
            hi = float(bar["high"])
            lo = float(bar["low"])
            holding = j - entry_i

            if direction == "long":
                if lo <= sl_price:
                    label = -1
                    exit_i = j
                    break
                if hi >= tp_price:
                    label = +1
                    exit_i = j
                    break
            else:
                if hi >= sl_price:
                    label = -1
                    exit_i = j
                    break
                if lo <= tp_price:
                    label = +1
                    exit_i = j
                    break

        exit_price = float(df.iloc[exit_i]["close"])
        pnl_pct = (
            (exit_price - entry_price) / entry_price
            if direction == "long"
            else (entry_price - exit_price) / entry_price
        )

        rows.append({
            "signal_ts": sig_ts,
            "direction": direction,
            "entry_bar_idx": entry_i,
            "t0": int(entry_i),
            "t1": int(exit_i),
            "label": int(label),
            "holding_bars": int(holding),
            "pnl_pct": float(pnl_pct),
        })

    result = pd.DataFrame(rows)
    if result.empty:
        return result

    pos = int((result["label"] == 1).sum())
    neg = int((result["label"] == -1).sum())
    neu = int((result["label"] == 0).sum())
    logger.bind(n_total=len(result), n_tp=pos, n_sl=neg, n_timeout=neu).info(
        "meta_labeling.triple_barrier.done"
    )
    return result


# =====================================================================
# 2. Feature engineering (lookahead-free)
# =====================================================================

def engineer_features(
    df: pd.DataFrame,
    signals: list[dict] | pd.DataFrame,
) -> pd.DataFrame:
    """Extract ML features at each signal bar (lookahead-free).

    Features extracted AT bar i (the signal bar — no future data):

    Bar features (computed on df up to bar i):
      - atr_pct       : ATR14 / close  (volatility)
      - kaufman_er    : Kaufman Efficiency Ratio (trend strength)
      - body_ratio    : |close-open| / (high-low)  of signal bar
      - close_to_ema20_pct : (close - ema20) / ema20
      - close_above_200ema : 1/0 boolean
      - volume_z      : volume z-score (60-bar rolling)

    Lookback features (rolling window behind bar i):
      - rolling_5d_return  : 5-bar log return
      - rolling_20d_return : 20-bar log return
      - rolling_5d_vol     : 5-bar std of daily returns

    Signal features (from signal metadata):
      - confluence_score      : signal's confluence_score
      - near_sr               : 1/0 whether near S/R level
      - swing_distance_atr    : distance to structural SL / ATR

    Context features:
      - rolling_60d_sharpe    : rolling 60-bar Sharpe at signal bar
    """
    if isinstance(signals, pd.DataFrame):
        sig_records = signals.to_dict("records")
    else:
        sig_records = list(signals)

    df = df.copy().reset_index(drop=True)
    df["ts"] = pd.to_datetime(df["ts"], utc=True)

    # Pre-compute rolling indicators on full df (past-only — safe because
    # we read them AT bar i, which was computed using [0..i])
    close = df["close"]
    log_ret = np.log(close / close.shift(1))

    df["_r5"] = log_ret.rolling(5, min_periods=2).sum()
    df["_r20"] = log_ret.rolling(20, min_periods=5).sum()
    df["_vol5"] = log_ret.rolling(5, min_periods=2).std(ddof=0)

    # EMA20 / EMA200
    if "ema20" not in df.columns:
        df["ema20"] = close.ewm(span=20, adjust=False).mean()
    if "ema200" not in df.columns:
        df["ema200"] = close.ewm(span=200, adjust=False).mean()

    # ATR if missing
    if "atr14" not in df.columns:
        hi, lo, pc = df["high"], df["low"], close.shift(1)
        tr = pd.concat([(hi - lo).abs(), (hi - pc).abs(), (lo - pc).abs()], axis=1).max(axis=1)
        df["atr14"] = tr.rolling(14, min_periods=1).mean()

    # Kaufman ER if missing
    if "kaufman_er" not in df.columns:
        period = 14
        chg = (close - close.shift(period)).abs()
        vol_sum = close.diff().abs().rolling(period, min_periods=period).sum()
        df["kaufman_er"] = (chg / vol_sum.replace(0, np.nan)).fillna(0.0).clip(0.0, 1.0)

    # Rolling Sharpe (60-bar)
    if "rolling_sharpe" not in df.columns:
        rets = close.pct_change()
        mu = rets.rolling(60, min_periods=20).mean()
        sd = rets.rolling(60, min_periods=20).std(ddof=0)
        df["rolling_sharpe"] = (mu / sd.replace(0, np.nan) * np.sqrt(365)).fillna(0.0)

    # Volume z-score (60-bar)
    if "vol_z" not in df.columns:
        vol = df["volume"]
        vmean = vol.rolling(60, min_periods=10).mean()
        vstd = vol.rolling(60, min_periods=10).std(ddof=0)
        df["vol_z"] = (vol - vmean) / vstd.replace(0, np.nan)

    ts_to_idx: dict[pd.Timestamp, int] = {
        pd.Timestamp(t): k for k, t in enumerate(df["ts"])
    }

    rows: list[dict[str, Any]] = []
    for sig in sig_records:
        sig_ts = pd.Timestamp(sig["ts"])
        if sig_ts.tzinfo is None:
            sig_ts = sig_ts.tz_localize("UTC")
        else:
            sig_ts = sig_ts.tz_convert("UTC")

        i = ts_to_idx.get(sig_ts)
        if i is None or i < 1:
            continue

        bar = df.iloc[i]
        c = float(bar["close"])
        o_price = float(bar["open"])
        hi_val = float(bar["high"])
        lo_val = float(bar["low"])
        atr = float(bar.get("atr14") or c * 0.01)
        rng = hi_val - lo_val
        body_ratio = abs(c - o_price) / rng if rng > 0 else 0.0

        ema20_val = float(bar.get("ema20") or c)
        ema200_val = float(bar.get("ema200") or c)
        close_to_ema20 = (c - ema20_val) / ema20_val if ema20_val != 0 else 0.0
        above_200ema = 1.0 if c > ema200_val else 0.0

        kaufman = float(bar.get("kaufman_er") or 0.0)
        vol_z = float(bar.get("vol_z") if "vol_z" in bar.index else 0.0) or 0.0
        sharpe60 = float(bar.get("rolling_sharpe") or 0.0)

        r5 = float(df.iloc[i]["_r5"]) if not np.isnan(df.iloc[i]["_r5"]) else 0.0
        r20 = float(df.iloc[i]["_r20"]) if not np.isnan(df.iloc[i]["_r20"]) else 0.0
        v5 = float(df.iloc[i]["_vol5"]) if not np.isnan(df.iloc[i]["_vol5"]) else 0.0

        # Signal features from metadata
        meta = sig.get("metadata") or {}
        confluence = float(sig.get("confluence_score") or 0.0)
        near_sr = float(bool(meta.get("near_sr", False)))

        sl_p = float(sig.get("sl_price") or 0.0)
        direction = str(sig.get("direction", "long"))
        if atr > 0 and sl_p > 0:
            if direction == "long":
                swing_dist_atr = (c - sl_p) / atr
            else:
                swing_dist_atr = (sl_p - c) / atr
        else:
            swing_dist_atr = 2.0  # default 2R fallback

        atr_pct = atr / c if c > 0 else 0.0

        rows.append({
            "signal_ts": sig_ts,
            "direction": direction,
            # bar features
            "atr_pct": float(atr_pct),
            "kaufman_er": float(kaufman),
            "body_ratio": float(body_ratio),
            "close_to_ema20_pct": float(close_to_ema20),
            "close_above_200ema": float(above_200ema),
            "volume_z": float(np.nan_to_num(vol_z, nan=0.0)),
            # lookback features
            "rolling_5d_return": float(r5),
            "rolling_20d_return": float(r20),
            "rolling_5d_vol": float(v5),
            # signal features
            "confluence_score": float(confluence),
            "near_sr": float(near_sr),
            "swing_distance_atr": float(swing_dist_atr),
            # context
            "rolling_60d_sharpe": float(sharpe60),
        })

    feat_df = pd.DataFrame(rows)
    if feat_df.empty:
        return feat_df
    feat_df = feat_df.set_index("signal_ts")
    feat_df = feat_df.replace([np.inf, -np.inf], np.nan)
    # Fill NaN with column medians (conservative — no future leak)
    for col in feat_df.columns:
        if col == "direction":
            continue
        feat_df[col] = feat_df[col].fillna(feat_df[col].median())
    logger.bind(n_signals=len(rows), n_features=len(feat_df.columns) - 1).info(
        "meta_labeling.engineer_features.done"
    )
    return feat_df


# =====================================================================
# 3. Sample weights — López uniqueness
# =====================================================================

def _compute_sample_weights(labels_df: pd.DataFrame) -> np.ndarray:
    """Compute uniqueness-based sample weights (López §3.5).

    For each label i with interval [t0_i, t1_i], compute:
        u_i = mean(1 / c_t) for t in [t0_i, t1_i]
    where c_t = number of labels whose interval contains bar t.

    Returns weight vector of same length as labels_df.
    """
    if labels_df.empty:
        return np.ones(0)

    n = len(labels_df)
    t0s = labels_df["t0"].values
    t1s = labels_df["t1"].values

    # For each bar index, count how many labels overlap it
    # Bar range: min(t0) to max(t1)
    if len(t0s) == 0:
        return np.ones(n)

    bar_min = int(t0s.min())
    bar_max = int(t1s.max())
    n_bars = bar_max - bar_min + 1

    # c_t: concurrent label count at bar t
    c_t = np.zeros(n_bars, dtype=float)
    for i in range(n):
        t0 = int(t0s[i]) - bar_min
        t1 = int(t1s[i]) - bar_min
        c_t[t0: t1 + 1] += 1.0

    # Uniqueness for each label
    weights = np.ones(n, dtype=float)
    for i in range(n):
        t0 = int(t0s[i]) - bar_min
        t1 = int(t1s[i]) - bar_min
        window = c_t[t0: t1 + 1]
        if len(window) > 0 and window.sum() > 0:
            # Average 1/c_t over the label's interval
            weights[i] = np.mean(1.0 / window[window > 0])

    # Normalize so sum = n (sklearn convention)
    total = weights.sum()
    if total > 0:
        weights = weights * n / total

    return weights.clip(0.0, None)


# =====================================================================
# 4. Purged k-fold CV
# =====================================================================

def _purged_kfold_splits(
    labels_df: pd.DataFrame,
    n_folds: int = 5,
    embargo_bars: int = 5,
) -> list[tuple[np.ndarray, np.ndarray]]:
    """Generate purged k-fold train/test index splits (López §5.2).

    Purging: remove from train any sample whose [t0, t1] overlaps
    the test fold's bar range.
    Embargo: additionally remove embargo_bars bars after the test fold.
    """
    n = len(labels_df)
    if n < n_folds * 3:
        # Not enough samples: fall back to simple sequential splits
        fold_size = max(1, n // n_folds)
        splits = []
        for f in range(n_folds):
            te = np.arange(f * fold_size, min((f + 1) * fold_size, n))
            tr = np.array([j for j in range(n) if j not in set(te)])
            if len(tr) > 0 and len(te) > 0:
                splits.append((tr, te))
        return splits

    t0s = labels_df["t0"].values
    t1s = labels_df["t1"].values

    # Split samples into n_folds groups based on their position (by t0)
    sorted_idx = np.argsort(t0s, kind="stable")
    groups = np.array_split(sorted_idx, n_folds)

    splits: list[tuple[np.ndarray, np.ndarray]] = []
    for f_idx, test_group in enumerate(groups):
        if len(test_group) == 0:
            continue

        te_t0_min = int(t0s[test_group].min())
        te_t1_max = int(t1s[test_group].max())
        embargo_end = te_t1_max + embargo_bars

        # Build train: all samples not in test that don't overlap test interval
        train_indices: list[int] = []
        for g_idx, group in enumerate(groups):
            if g_idx == f_idx:
                continue  # skip test group
            for idx in group:
                si_t0 = int(t0s[idx])
                si_t1 = int(t1s[idx])
                # Purge: label overlaps test window
                overlaps = si_t1 >= te_t0_min and si_t0 <= te_t1_max
                # Embargo: label starts within embargo period after test
                in_embargo = si_t0 <= embargo_end and si_t0 > te_t1_max
                if not overlaps and not in_embargo:
                    train_indices.append(int(idx))

        if len(train_indices) > 0 and len(test_group) > 0:
            splits.append((np.array(train_indices), test_group.astype(int)))

    return splits


# =====================================================================
# 5. Train Random Forest with purged CV
# =====================================================================

def train_rf(
    X: pd.DataFrame,
    y: pd.Series,
    labels_df: pd.DataFrame | None = None,
    *,
    cv: int = 5,
    n_estimators: int = 200,
    max_depth: int = 6,
    min_samples_leaf: int = 5,
    random_state: int = 42,
    embargo_bars: int = 5,
) -> tuple[Any, dict[str, Any]]:
    """Train Random Forest with purged k-fold CV (López §5.2).

    Parameters
    ----------
    X          : feature matrix (n_samples x n_features), index = signal_ts
    y          : binary labels (1 = win, 0 = loss/timeout), same index
    labels_df  : DataFrame from triple_barrier_labels with [t0, t1] columns.
                 Used for purging and uniqueness weighting.
                 If None, simple sequential CV is used.
    cv         : number of folds
    Returns
    -------
    (fitted_model, metrics_dict)
    """
    if not _SKLEARN_OK:
        raise RuntimeError("scikit-learn not installed — pip install scikit-learn")

    X = X.copy()
    y = y.copy()

    # Drop non-numeric columns (direction etc.)
    feat_cols = [c for c in X.columns if c != "direction"]
    X_num = X[feat_cols].astype(float)

    # Align X and y (handle potential duplicate timestamps from multi-symbol data
    # by resetting to integer index and aligning by position)
    X_num = X_num.reset_index(drop=True)
    y_aligned = y.reset_index(drop=True)

    # Trim to common length (both should be same size, but guard against mismatch)
    min_len = min(len(X_num), len(y_aligned))
    X_num = X_num.iloc[:min_len]
    y_aligned = y_aligned.iloc[:min_len]

    n_samples = len(X_num)
    if n_samples < 10:
        raise ValueError(f"Too few samples to train RF: {n_samples}")

    # Sample weights via uniqueness (López §3.5)
    if labels_df is not None and not labels_df.empty:
        # Align labels_df to same integer positions as X_num
        ldf = labels_df.copy().reset_index(drop=True)
        if "signal_ts" in ldf.columns:
            ldf["signal_ts"] = pd.to_datetime(ldf["signal_ts"], utc=True)
        ldf = ldf.iloc[:min_len]
        for col in ["t0", "t1"]:
            if col in ldf.columns:
                ldf[col] = ldf[col].fillna(0).astype(int)
        sample_weights = _compute_sample_weights(ldf)
        splits = _purged_kfold_splits(ldf, n_folds=cv, embargo_bars=embargo_bars)
    else:
        sample_weights = np.ones(n_samples)

    # Purged CV splits (fallback if not computed above)
    if labels_df is None or labels_df.empty:
        # Simple sequential splits as fallback
        fold_size = max(1, n_samples // cv)
        splits = []
        for f in range(cv):
            te = np.arange(f * fold_size, min((f + 1) * fold_size, n_samples))
            tr = np.array([j for j in range(n_samples) if j not in set(te)])
            if len(tr) > 0 and len(te) > 0:
                splits.append((tr, te))

    # Purged CV evaluation
    fold_accs: list[float] = []
    fold_aucs: list[float] = []
    fold_precs: list[float] = []

    X_arr = X_num.values
    y_arr = y_aligned.values.astype(int)

    for fold_i, (tr_idx, te_idx) in enumerate(splits):
        if len(tr_idx) < 5 or len(te_idx) < 2:
            continue
        X_tr, X_te = X_arr[tr_idx], X_arr[te_idx]
        y_tr, y_te = y_arr[tr_idx], y_arr[te_idx]
        w_tr = sample_weights[tr_idx]

        clf_fold = RandomForestClassifier(
            n_estimators=n_estimators,
            max_depth=max_depth,
            min_samples_leaf=min_samples_leaf,
            n_jobs=-1,
            random_state=random_state,
            class_weight="balanced",
        )
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            clf_fold.fit(X_tr, y_tr, sample_weight=w_tr)

        prob = clf_fold.predict_proba(X_te)[:, 1]
        pred = (prob >= 0.5).astype(int)
        acc = float(accuracy_score(y_te, pred))
        fold_accs.append(acc)

        # AUC (only if both classes present)
        if len(np.unique(y_te)) >= 2:
            auc = float(roc_auc_score(y_te, prob))
            fold_aucs.append(auc)

        # Precision (true positives / predicted positives)
        tp = int(((pred == 1) & (y_te == 1)).sum())
        pp = int((pred == 1).sum())
        if pp > 0:
            fold_precs.append(tp / pp)

        logger.bind(
            fold=fold_i, acc=round(acc, 3),
            n_tr=len(tr_idx), n_te=len(te_idx),
        ).info("meta_labeling.rf.fold")

    # Train final model on all data
    clf_final = RandomForestClassifier(
        n_estimators=n_estimators,
        max_depth=max_depth,
        min_samples_leaf=min_samples_leaf,
        n_jobs=-1,
        random_state=random_state,
        class_weight="balanced",
    )
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        clf_final.fit(X_arr, y_arr, sample_weight=sample_weights)

    train_prob = clf_final.predict_proba(X_arr)[:, 1]
    train_pred = (train_prob >= 0.5).astype(int)
    train_acc = float(accuracy_score(y_arr, train_pred))

    # Feature importance
    importance = dict(zip(feat_cols, clf_final.feature_importances_.tolist()))
    importance_sorted = dict(
        sorted(importance.items(), key=lambda x: x[1], reverse=True)
    )

    metrics = {
        "train_accuracy": train_acc,
        "cv_mean_accuracy": float(np.mean(fold_accs)) if fold_accs else float("nan"),
        "cv_std_accuracy": float(np.std(fold_accs)) if fold_accs else float("nan"),
        "cv_mean_auc": float(np.mean(fold_aucs)) if fold_aucs else float("nan"),
        "cv_mean_precision": float(np.mean(fold_precs)) if fold_precs else float("nan"),
        "n_samples": n_samples,
        "n_folds": cv,
        "n_folds_run": len(fold_accs),
        "feature_importance": importance_sorted,
        "feature_names": feat_cols,
        "label_balance": float(y_arr.mean()),
    }

    logger.bind(
        train_acc=round(train_acc, 3),
        cv_mean=round(metrics["cv_mean_accuracy"], 3),
        n_samples=n_samples,
    ).info("meta_labeling.rf.trained")

    return clf_final, metrics


# =====================================================================
# 6. Inference: predict_filter
# =====================================================================

def predict_filter(
    model: Any,
    X: pd.DataFrame,
    *,
    threshold: float = 0.55,
    feature_names: list[str] | None = None,
) -> pd.Series:
    """Apply trained RF to generate a boolean trade filter mask.

    Parameters
    ----------
    model          : fitted sklearn classifier with predict_proba
    X              : feature DataFrame (same columns as training)
    threshold      : probability threshold — take trade if P(win) >= threshold
    feature_names  : feature column names used in training (for alignment)

    Returns
    -------
    pd.Series (bool), index = X.index
        True  = take the trade (predicted win probability >= threshold)
        False = skip (filter out false positive)
    """
    if not _SKLEARN_OK:
        raise RuntimeError("scikit-learn not installed")

    feat_cols = feature_names or [c for c in X.columns if c != "direction"]
    X_num = X[feat_cols].astype(float)
    X_num = X_num.replace([np.inf, -np.inf], np.nan)
    X_num = X_num.fillna(0.0)

    probs = model.predict_proba(X_num.values)[:, 1]
    mask = pd.Series(probs >= threshold, index=X.index, name="ml_filter")

    n_taken = int(mask.sum())
    n_total = len(mask)
    logger.bind(
        threshold=threshold, n_taken=n_taken, n_total=n_total,
        pct_taken=round(n_taken / max(n_total, 1) * 100, 1),
    ).info("meta_labeling.predict_filter")

    return mask


# =====================================================================
# 7. Convenience: serialize / deserialize model
# =====================================================================

def save_model(model: Any, metrics: dict, path: str) -> None:
    """Serialize model + metrics with joblib."""
    import joblib
    import json
    from pathlib import Path

    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump({"model": model, "metrics": metrics}, str(p))
    meta_path = p.with_suffix(".meta.json")
    # Save metrics (without feature_importance detail for readability)
    summary = {k: v for k, v in metrics.items() if k != "feature_importance"}
    meta_path.write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")
    logger.bind(path=str(p)).info("meta_labeling.model.saved")


def load_model(path: str) -> tuple[Any, dict]:
    """Load model + metrics from joblib file."""
    import joblib
    payload = joblib.load(path)
    return payload["model"], payload.get("metrics", {})


__all__ = [
    "triple_barrier_labels",
    "engineer_features",
    "train_rf",
    "predict_filter",
    "save_model",
    "load_model",
]
