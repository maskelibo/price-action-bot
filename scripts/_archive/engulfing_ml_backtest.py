"""López de Prado meta-labeling backtest for engulfing_continuation.

Methodology:
  - First 60% of chronologically sorted trades  → train Random Forest
  - Last  40% of trades (OOS)                   → honest evaluation

This is a POSTPROCESSING filter: the strategy itself is unchanged.
The RF predicts which engulfing signals will succeed (TP hit).

Critical evaluation principle (López):
  If the ML filter HURTS performance, it is REPORTED CLEARLY.
  No threshold-tweaking to make results look better.

Run:
    PYTHONPATH=src PYTHONIOENCODING=utf-8 python scripts/engulfing_ml_backtest.py
"""
from __future__ import annotations

import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


# =====================================================================
# Helpers
# =====================================================================

def _make_manifest():
    """Tuned engulfing_continuation manifest (same as run_engulfing_backtest.py)."""
    from price_action.strategies.base import StrategyManifest
    raw = {
        "name": "engulfing_continuation",
        "version": "1.0.0",
        "description": "Engulfing bar after 20-EMA pullback in established trend",
        "trend_filter": {"type": "ema", "period": 50, "required": True},
        "signals": {
            "patterns": [
                {
                    "id": "bullish_engulfing_cont",
                    "enabled": True,
                    "weight": 1.5,
                    "params": {"body_ratio_min": 0.6, "pullback_window": 10, "pullback_touch_atr": 0.5},
                },
                {
                    "id": "bearish_engulfing_cont",
                    "enabled": True,
                    "weight": 1.5,
                    "params": {"body_ratio_min": 0.6, "pullback_window": 10, "pullback_touch_atr": 0.5},
                },
            ],
            "structure": {
                "swing": {"fractal_n": 2},
                "support_resistance": {
                    "lookback_bars": 120,
                    "cluster_atr_multiplier": 0.5,
                    "min_touches": 2,
                    "max_age_bars": 120,
                },
                "require_proximity_to_sr_atr": 0.5,
            },
            "filters": {
                "atr_min_pct": 0.005,
                "volume_zscore_min": 0.0,
                "kaufman_er_period": 14,
                "kaufman_er_min": 0.20,
                "bear_regime_size_factor": 0.5,
            },
            "confluence": {
                "method": "weighted_sum",
                "min_score": 1.5,
                "bonus_if_at_sr": 0.5,
            },
        },
        "risk": {
            "stop_loss": {"method": "structural", "swing_lookback": 10},
            "take_profit": {"method": "r_multiple", "primary_R": 2.0},
            "position_sizing": {"method": "fixed_fractional", "risk_per_trade": 0.01},
        },
    }
    return StrategyManifest.model_validate(raw)


def _load_ohlcv(symbol: str, tf: str = "1d") -> pd.DataFrame:
    """Load OHLCV from DuckDB market store."""
    try:
        import duckdb
        con = duckdb.connect(str(ROOT / "data" / "market.duckdb"), read_only=True)
        df = con.execute(
            "SELECT ts, open, high, low, close, volume FROM ohlcv "
            "WHERE venue='binance' AND symbol=? AND timeframe=? ORDER BY ts",
            [symbol, tf],
        ).fetchdf()
        con.close()
    except Exception as exc:
        print(f"  [WARN] Cannot load {symbol}: {exc}")
        return pd.DataFrame()
    if df.empty:
        return df
    df["ts"] = pd.to_datetime(df["ts"], utc=True)
    df["symbol"] = symbol
    df["timeframe"] = tf
    df["venue"] = "binance"
    return df


def _signals_to_dicts(signals) -> list[dict]:
    """Convert Signal objects to plain dicts for meta-labeling."""
    out = []
    for sig in signals:
        out.append({
            "ts": sig.ts,
            "direction": sig.direction,
            "sl_price": sig.sl_price,
            "tp_price": sig.tp_price,
            "confluence_score": sig.confluence_score,
            "metadata": sig.metadata or {},
        })
    return out


def _simulate_signals_direct(
    df_feats: pd.DataFrame,
    signals: list,
    *,
    initial_capital: float = 10_000.0,
    slippage_bps: float = 5.0,
    fees: dict | None = None,
) -> pd.DataFrame:
    """Lightweight bar-by-bar simulator on a GIVEN signal list (no internal re-generation).

    This bypasses BacktestEngine.run() which would regenerate signals internally.
    Uses identical SL/TP/fee logic as BacktestEngine._simulate_symbol.

    Returns: trades DataFrame (same columns as BacktestEngine output).
    """
    if not signals or df_feats.empty:
        return pd.DataFrame()

    fees = fees or {"taker": 0.00075, "maker": -0.00010}
    slip = slippage_bps / 10_000.0
    fee_rate = fees.get("taker", 0.00075)

    df = df_feats.reset_index(drop=True)
    idx_by_ts = {pd.Timestamp(t).tz_convert("UTC"): i for i, t in enumerate(df["ts"])}

    from price_action.contracts import stable_hash

    signals_sorted = sorted(signals, key=lambda s: s.ts)
    trades: list[dict] = []
    equity = initial_capital
    in_position = False

    for sig in signals_sorted:
        if in_position:
            continue
        sig_ts = pd.Timestamp(sig.ts)
        if sig_ts.tzinfo is None:
            sig_ts = sig_ts.tz_localize("UTC")
        else:
            sig_ts = sig_ts.tz_convert("UTC")

        i = idx_by_ts.get(sig_ts)
        if i is None or i + 1 >= len(df):
            continue

        entry_bar = df.iloc[i + 1]
        entry_price = float(entry_bar["open"])
        if sig.direction == "long":
            entry_price *= (1 + slip)
        else:
            entry_price *= (1 - slip)

        sl_dist = abs(entry_price - sig.sl_price)
        if sl_dist <= 0:
            continue

        risk_dollar = equity * 0.01
        qty = risk_dollar / sl_dist
        if qty <= 0:
            continue

        sl_price = sig.sl_price
        tp_price = sig.tp_price
        in_position = True
        entry_idx = i + 1
        entry_ts_val = pd.Timestamp(entry_bar["ts"])

        exit_idx = len(df) - 1
        exit_price = float(df.iloc[-1]["close"])
        mae = 0.0
        mfe = 0.0

        for j in range(entry_idx, len(df)):
            bar = df.iloc[j]
            hi = float(bar["high"])
            lo = float(bar["low"])
            if sig.direction == "long":
                mae = min(mae, (lo - entry_price) / entry_price)
                mfe = max(mfe, (hi - entry_price) / entry_price)
                if lo <= sl_price:
                    exit_idx = j
                    exit_price = sl_price * (1 - slip)
                    break
                if hi >= tp_price:
                    exit_idx = j
                    exit_price = tp_price * (1 - slip)
                    break
            else:
                mae = max(mae, (hi - entry_price) / entry_price)
                mfe = min(mfe, (lo - entry_price) / entry_price)
                if hi >= sl_price:
                    exit_idx = j
                    exit_price = sl_price * (1 + slip)
                    break
                if lo <= tp_price:
                    exit_idx = j
                    exit_price = tp_price * (1 + slip)
                    break

        exit_ts_val = pd.Timestamp(df.iloc[exit_idx]["ts"])

        pnl_per_unit = (
            exit_price - entry_price if sig.direction == "long"
            else entry_price - exit_price
        )
        gross = pnl_per_unit * qty
        fee_total = (entry_price + exit_price) * qty * fee_rate
        net = gross - fee_total

        initial_risk = abs(entry_price - sl_price) * qty
        r_multiple = net / initial_risk if initial_risk > 0 else 0.0

        trade_id = stable_hash((sig.symbol, str(sig.ts), entry_price))
        trades.append({
            "trade_id": trade_id,
            "venue": sig.venue,
            "symbol": sig.symbol,
            "side": sig.direction,
            "entry_ts": entry_ts_val,
            "exit_ts": exit_ts_val,
            "entry_price": entry_price,
            "exit_price": exit_price,
            "quantity": qty,
            "realized_pnl_usdt": net,
            "realized_r_multiple": r_multiple,
            "fees_usdt": fee_total,
            "slippage_bps": slippage_bps,
            "strategy_id": "engulfing_continuation",
            "pattern_id": sig.pattern_id,
            "confluence_score": sig.confluence_score,
            "initial_sl": sl_price,
            "initial_tp": tp_price,
            "mae_pct": mae,
            "mfe_pct": mfe,
        })
        equity += net
        in_position = False

    return pd.DataFrame(trades)


def _equity_from_trades(
    trades_df: pd.DataFrame,
    *,
    initial_capital: float = 10_000.0,
) -> tuple[float, float]:
    """Compute final equity and CAGR from a trades DataFrame."""
    if trades_df.empty:
        return initial_capital, 0.0
    net = float(trades_df["realized_pnl_usdt"].sum())
    final_eq = initial_capital + net

    # CAGR: estimate from first entry to last exit
    entry_ts = pd.to_datetime(trades_df["entry_ts"]).min()
    exit_ts = pd.to_datetime(trades_df["exit_ts"]).max()
    years = max((exit_ts - entry_ts).days / 365.25, 0.01)
    cagr = (final_eq / initial_capital) ** (1 / years) - 1.0
    return final_eq, cagr


def _win_rate_from_trades(trades_df: pd.DataFrame) -> float:
    if trades_df.empty:
        return 0.0
    return float((trades_df["realized_pnl_usdt"] > 0).mean())


def _compute_dsr(trades_df: pd.DataFrame, n_trials: int = 1) -> float:
    """Compute Deflated Sharpe Ratio for a trades DataFrame."""
    from price_action.backtest.metrics import deflated_sharpe_ratio
    if trades_df.empty or len(trades_df) < 3:
        return 0.0
    pnls = trades_df["realized_pnl_usdt"]
    if pnls.std() == 0:
        return 0.0
    sr = float(pnls.mean() / pnls.std() * np.sqrt(252))
    skew = float(pnls.skew())
    kurt = float(pnls.kurt()) + 3.0
    return deflated_sharpe_ratio(
        sr, n_trials=max(n_trials, 2), skew=skew, kurt=kurt, n_obs=len(pnls)
    )


def _sharpe_from_trades(trades_df: pd.DataFrame) -> float:
    """Annualized Sharpe from per-trade PnL series (proxy)."""
    if trades_df.empty or len(trades_df) < 3:
        return 0.0
    pnls = trades_df["realized_pnl_usdt"]
    if pnls.std() == 0:
        return 0.0
    return float(pnls.mean() / pnls.std() * np.sqrt(252))


# =====================================================================
# Main backtest pipeline
# =====================================================================

SYMBOLS = [
    "BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT", "XRP/USDT",
    "DOGE/USDT", "ADA/USDT", "AVAX/USDT", "LINK/USDT", "DOT/USDT",
]

THRESHOLD = 0.55       # RF filter threshold
TRAIN_SPLIT = 0.60     # First 60% trades = train
INITIAL_CAPITAL = 10_000.0


def main() -> int:
    from price_action.ml.meta_labeling import (
        engineer_features,
        predict_filter,
        train_rf,
        triple_barrier_labels,
    )
    from price_action.strategies.engulfing_continuation import EngulfingContinuationStrategy

    print("=" * 72)
    print("  López de Prado Meta-Labeling — engulfing_continuation ML filter")
    print("=" * 72)
    print(f"  Symbols     : {len(SYMBOLS)} USDT pairs")
    print(f"  Train split : first {int(TRAIN_SPLIT*100)}% trades")
    print(f"  OOS split   : last  {int((1-TRAIN_SPLIT)*100)}% trades")
    print(f"  RF threshold: {THRESHOLD}")
    print(f"  Initial cap : ${INITIAL_CAPITAL:,.0f} per symbol")
    print()

    manifest = _make_manifest()

    # ---- Step 1: Gather all signals + features across all symbols ----
    all_signals_dicts: list[dict] = []
    all_features: list[pd.DataFrame] = []
    all_labels: list[pd.DataFrame] = []
    sym_data: dict[str, dict] = {}  # symbol -> {df_feats, signals, features, labels}

    print("Step 1: Generating signals and features for all symbols...")
    for sym in SYMBOLS:
        df = _load_ohlcv(sym)
        if df.empty:
            print(f"  {sym:<12} [SKIP] no data")
            continue
        strategy = EngulfingContinuationStrategy(manifest)
        try:
            df_feats = strategy.prepare_features(df)
            signals = strategy.generate_signals(df_feats)
        except Exception as exc:
            print(f"  {sym:<12} [ERROR] {exc}")
            continue

        if not signals:
            print(f"  {sym:<12} [SKIP] no signals")
            continue

        sig_dicts = _signals_to_dicts(signals)
        feats = engineer_features(df_feats, sig_dicts)
        labels = triple_barrier_labels(
            df_feats, sig_dicts, atr_mult_tp=2.0, atr_mult_sl=1.0, max_holding=20
        )

        if feats.empty or labels.empty:
            print(f"  {sym:<12} [SKIP] empty features/labels")
            continue

        print(f"  {sym:<12} signals={len(signals):>3}, features={len(feats):>3}, labels={len(labels):>3}")
        sym_data[sym] = {
            "df_feats": df_feats,
            "signals": signals,
            "sig_dicts": sig_dicts,
            "features": feats,
            "labels": labels,
        }
        all_signals_dicts.extend(sig_dicts)
        all_features.append(feats)
        all_labels.append(labels)

    if not all_features:
        print("\n[ERROR] No data available. Check database path.")
        return 1

    # ---- Step 2: Combine all symbols for training ----
    # Use integer index to handle multi-symbol duplicate timestamps.
    # Track (symbol, ts) pairs for OOS per-signal filtering.
    X_parts: list[pd.DataFrame] = []
    labels_parts: list[pd.DataFrame] = []
    symbol_ts_pairs: list[tuple[str, pd.Timestamp]] = []  # (sym, ts) for each row

    for sym, data in sym_data.items():
        feats = data["features"].copy()
        labs = data["labels"].copy()
        feats["_sym"] = sym
        feats["_ts"] = feats.index
        X_parts.append(feats)
        labs["_sym"] = sym
        labs["signal_ts"] = pd.to_datetime(labs["signal_ts"], utc=True)
        labels_parts.append(labs)

    X_all = pd.concat(X_parts, ignore_index=True)
    labels_all = pd.concat(labels_parts, ignore_index=True)

    # Sort chronologically
    sort_order = X_all["_ts"].argsort()
    X_all = X_all.iloc[sort_order].reset_index(drop=True)
    labels_all = labels_all.sort_values("signal_ts").reset_index(drop=True)

    # Extract tracking cols before dropping
    signal_ts_col = pd.to_datetime(X_all["_ts"]).dt.tz_localize("UTC") if pd.to_datetime(X_all["_ts"]).dt.tz is None else pd.to_datetime(X_all["_ts"]).dt.tz_convert("UTC")
    signal_sym_col = X_all["_sym"].values
    X_all = X_all.drop(columns=["_sym", "_ts"])

    # Drop direction column (string) from features before ML
    if "direction" in X_all.columns:
        X_all = X_all.drop(columns=["direction"])

    # Binary label: 1 = TP hit, 0 = SL or timeout
    # Ensure same length (trim to shorter)
    min_len = min(len(X_all), len(labels_all))
    X_all = X_all.iloc[:min_len].reset_index(drop=True)
    labels_all = labels_all.iloc[:min_len].reset_index(drop=True)
    signal_ts_col = signal_ts_col.iloc[:min_len]
    signal_sym_col = signal_sym_col[:min_len]

    y_all = (labels_all["label"] == 1).astype(int)

    total_samples = len(X_all)
    n_train = int(total_samples * TRAIN_SPLIT)
    n_oos = total_samples - n_train

    print(f"\n  Total labeled samples : {total_samples}")
    print(f"  Train (IS) samples    : {n_train}  ({TRAIN_SPLIT*100:.0f}%)")
    print(f"  OOS test samples      : {n_oos}   ({(1-TRAIN_SPLIT)*100:.0f}%)")
    print(f"  Overall label balance : {y_all.mean():.1%} wins")

    if n_train < 15:
        print(f"\n[ERROR] Too few training samples: {n_train}. Need at least 15.")
        return 1

    # Chronological split by integer position (already sorted by ts)
    train_positions = np.arange(n_train)
    oos_positions = np.arange(n_train, total_samples)
    # OOS timestamps for signal filtering (keep as Series for .iloc access)
    oos_signal_ts = signal_ts_col.reset_index(drop=True).iloc[oos_positions].reset_index(drop=True)

    # Integer-based train/OOS split
    X_train = X_all.iloc[:n_train].copy()
    y_train = y_all.iloc[:n_train].copy()
    X_oos = X_all.iloc[n_train:].copy()
    y_oos = y_all.iloc[n_train:].copy()
    labels_train_df = labels_all.iloc[:n_train].copy()

    # ---- Step 3: Train RF ----
    print("\nStep 2: Training Random Forest with purged 5-fold CV (López)...")
    print(f"  n_estimators=200, max_depth=6, min_samples_leaf=5")
    print(f"  Sample weights = uniqueness (López §3.5)")
    print(f"  Purged CV: embargo = 5 bars after each test fold")

    model, train_metrics = train_rf(
        X_train,
        y_train,
        labels_df=labels_train_df,
        cv=5,
        n_estimators=200,
        max_depth=6,
        min_samples_leaf=5,
        random_state=42,
        embargo_bars=5,
    )

    print(f"\n  --- IN-SAMPLE METRICS ---")
    print(f"  Train accuracy       : {train_metrics['train_accuracy']:.3f}")
    print(f"  CV mean accuracy     : {train_metrics['cv_mean_accuracy']:.3f}")
    print(f"  CV std accuracy      : {train_metrics['cv_std_accuracy']:.3f}")
    print(f"  CV mean AUC          : {train_metrics['cv_mean_auc']:.3f}")
    print(f"  CV mean precision    : {train_metrics['cv_mean_precision']:.3f}")
    print(f"  n_folds run          : {train_metrics['n_folds_run']}/{train_metrics['n_folds']}")
    print(f"  Label balance (IS)   : {train_metrics['label_balance']:.1%} wins")

    print(f"\n  Top-5 feature importances:")
    imp = train_metrics.get("feature_importance", {})
    for feat, score in list(imp.items())[:5]:
        bar = "#" * int(score * 40)
        print(f"    {feat:<30} {score:.4f}  {bar}")

    # ---- Step 4: Apply filter on OOS set ----
    print(f"\nStep 3: OOS evaluation (threshold={THRESHOLD})...")

    feat_names = train_metrics.get("feature_names", [])
    if X_oos.empty:
        print("[ERROR] No OOS samples.")
        return 1

    oos_filter_mask = predict_filter(model, X_oos, threshold=THRESHOLD, feature_names=feat_names)

    def _to_utc(ts) -> pd.Timestamp:
        """Normalize timestamp to UTC-aware Timestamp."""
        t = pd.Timestamp(ts)
        if t.tzinfo is None:
            return t.tz_localize("UTC")
        return t.tz_convert("UTC")

    # Build set of (symbol, ts) pairs that passed the filter — per-symbol tracking
    filtered_sym_ts_set: set[tuple[str, pd.Timestamp]] = set()
    oos_sym_col = signal_sym_col[n_train:min_len]
    for pos_i, kept in enumerate(oos_filter_mask.values):
        if kept and pos_i < len(oos_signal_ts) and pos_i < len(oos_sym_col):
            filtered_sym_ts_set.add((oos_sym_col[pos_i], _to_utc(oos_signal_ts.iloc[pos_i])))

    # OOS cutoff: earliest timestamp among OOS signals (UTC-aware)
    oos_cutoff = (
        _to_utc(oos_signal_ts.min()) if len(oos_signal_ts) > 0 else None
    )

    # ---- Step 5: Per-symbol OOS backtest ----
    print("\nStep 4: Per-symbol OOS backtest (filtered vs unfiltered)...")

    all_oos_trades_unfiltered: list[pd.DataFrame] = []
    all_oos_trades_filtered: list[pd.DataFrame] = []

    for sym, data in sym_data.items():
        df_feats = data["df_feats"]
        signals = data["signals"]

        if oos_cutoff is None:
            continue

        # Separate signals into OOS by timestamp
        oos_signals_all = [
            s for s in signals
            if _to_utc(s.ts) >= oos_cutoff
        ]
        if not oos_signals_all:
            continue

        # Filtered signals: only take if RF says yes for THIS (sym, ts) pair
        oos_signals_filtered = [
            s for s in oos_signals_all
            if (sym, _to_utc(s.ts)) in filtered_sym_ts_set
        ]

        # Simulate unfiltered OOS (all OOS signals for this symbol)
        try:
            df_unf = _simulate_signals_direct(
                df_feats, oos_signals_all,
                initial_capital=INITIAL_CAPITAL,
            )
            if not df_unf.empty:
                all_oos_trades_unfiltered.append(df_unf)
        except Exception as exc:
            print(f"  {sym:<12} unfiltered backtest error: {exc}")
            import traceback; traceback.print_exc()

        # Simulate filtered OOS (RF-approved signals only)
        if oos_signals_filtered:
            try:
                df_flt = _simulate_signals_direct(
                    df_feats, oos_signals_filtered,
                    initial_capital=INITIAL_CAPITAL,
                )
                if not df_flt.empty:
                    all_oos_trades_filtered.append(df_flt)
            except Exception as exc:
                print(f"  {sym:<12} filtered backtest error: {exc}")

    # ---- Step 6: Aggregate OOS results ----
    trades_unf = (
        pd.concat(all_oos_trades_unfiltered, ignore_index=True)
        if all_oos_trades_unfiltered else pd.DataFrame()
    )
    trades_flt = (
        pd.concat(all_oos_trades_filtered, ignore_index=True)
        if all_oos_trades_filtered else pd.DataFrame()
    )

    n_syms_with_data = len(sym_data)

    # Equity calculation: sum across all symbols (each starts with $10K)
    def _total_equity_and_cagr(trades_df: pd.DataFrame) -> tuple[float, float]:
        if trades_df.empty:
            return INITIAL_CAPITAL * n_syms_with_data, 0.0
        total_pnl = float(trades_df["realized_pnl_usdt"].sum())
        total_start = INITIAL_CAPITAL * n_syms_with_data
        total_end = total_start + total_pnl
        # Use actual date range
        try:
            entry_ts_min = pd.to_datetime(trades_df["entry_ts"]).min()
            exit_ts_max = pd.to_datetime(trades_df["exit_ts"]).max()
            years = max((exit_ts_max - entry_ts_min).days / 365.25, 0.25)
        except Exception:
            years = 1.0
        cagr = (total_end / total_start) ** (1 / years) - 1.0 if total_start > 0 else 0.0
        return total_end, cagr

    eq_unf, cagr_unf = _total_equity_and_cagr(trades_unf)
    eq_flt, cagr_flt = _total_equity_and_cagr(trades_flt)

    wr_unf = _win_rate_from_trades(trades_unf)
    wr_flt = _win_rate_from_trades(trades_flt)

    n_trades_unf = len(trades_unf)
    n_trades_flt = len(trades_flt)

    dsr_unf = _compute_dsr(trades_unf, n_trials=1)
    dsr_flt = _compute_dsr(trades_flt, n_trials=2)  # 2 trials: original + RF

    sharpe_unf = _sharpe_from_trades(trades_unf)
    sharpe_flt = _sharpe_from_trades(trades_flt)

    # OOS label accuracy (how many our model predicted correct direction)
    y_oos_arr = y_oos.values
    oos_pred = oos_filter_mask.values
    oos_preds_on_all = np.zeros(len(y_oos_arr), dtype=bool)
    oos_preds_on_all[:len(oos_pred)] = oos_pred
    oos_acc = float((oos_preds_on_all.astype(int) == y_oos_arr[:len(oos_preds_on_all)]).mean())

    # Precision among taken trades
    taken_mask = oos_filter_mask.values
    y_oos_arr_aligned = y_oos.values[:len(taken_mask)]
    if taken_mask.sum() > 0:
        oos_precision = float(y_oos_arr_aligned[taken_mask].mean())
    else:
        oos_precision = 0.0

    # ---- Step 7: Report ----
    print("\n" + "=" * 72)
    print("  OUT-OF-SAMPLE RESULTS (HONEST — no threshold tweak)")
    print("=" * 72)

    start_unf = INITIAL_CAPITAL * n_syms_with_data
    print(f"\n  {'Metric':<30} {'Unfiltered':>12} {'RF Filtered':>12}")
    print(f"  {'-'*55}")
    print(f"  {'OOS trades (portfolio)':30} {n_trades_unf:>12,} {n_trades_flt:>12,}")
    pct_kept = n_trades_flt / max(n_trades_unf, 1) * 100
    print(f"  {'% signals kept':30} {'100%':>12} {pct_kept:>11.1f}%")
    print(f"  {'Win rate':30} {wr_unf:>11.1%} {wr_flt:>11.1%}")
    print(f"  {'Starting equity (total)':30} ${start_unf:>10,.0f} ${start_unf:>10,.0f}")
    print(f"  {'Final equity (total)':30} ${eq_unf:>10,.0f} ${eq_flt:>10,.0f}")
    print(f"  {'Annual return':30} {cagr_unf:>11.1%} {cagr_flt:>11.1%}")
    print(f"  {'Sharpe (trade-based)':30} {sharpe_unf:>12.2f} {sharpe_flt:>12.2f}")
    print(f"  {'Deflated Sharpe (DSR)':30} {dsr_unf:>12.3f} {dsr_flt:>12.3f}")

    print(f"\n  OOS ML metrics:")
    print(f"    OOS filter accuracy     : {oos_acc:.3f}")
    print(f"    OOS precision (taken)   : {oos_precision:.3f}")
    print(f"    OOS label balance       : {y_oos.mean():.1%} actual wins")

    # ---- Step 8: Verdict ----
    print("\n" + "=" * 72)
    print("  VERDICT")
    print("=" * 72)

    yearly_unf_pct = cagr_unf * 100
    yearly_flt_pct = cagr_flt * 100

    improved = yearly_flt_pct > yearly_unf_pct
    wr_improved = wr_flt > wr_unf
    dsr_improved = dsr_flt > dsr_unf
    trades_reduced = n_trades_flt < n_trades_unf

    if improved:
        print(f"\n  ML filter IMPROVED engulfing yearly: {yearly_unf_pct:.1f}% → {yearly_flt_pct:.1f}%")
    else:
        print(f"\n  ML filter HURT engulfing yearly: {yearly_unf_pct:.1f}% → {yearly_flt_pct:.1f}% — consider abandoning")

    print(f"\n  Win rate change  : {wr_unf:.1%} → {wr_flt:.1%}  ({'↑' if wr_improved else '↓'})")
    print(f"  DSR change       : {dsr_unf:.3f} → {dsr_flt:.3f}  ({'↑' if dsr_improved else '↓'})")
    print(f"  Trades filtered  : {n_trades_unf} → {n_trades_flt}  ({'-' if trades_reduced else '+no change'})")

    # ---- Step 9: Critical assessment ----
    print("\n" + "=" * 72)
    print("  CRITICAL ASSESSMENT")
    print("=" * 72)

    print(f"""
  Train accuracy  {train_metrics['train_accuracy']:.3f} vs CV mean {train_metrics['cv_mean_accuracy']:.3f}
  IS vs CV gap    {train_metrics['train_accuracy'] - train_metrics['cv_mean_accuracy']:.3f}
  (gap > 0.15 = suspicious overfitting on IS)

  OOS precision   {oos_precision:.3f}  (target ≥ 0.55 per López)
  OOS accuracy    {oos_acc:.3f}
  DSR filtered    {dsr_flt:.3f}  (López: > 0.6 = acceptable, > 0.95 = strong)
  """)

    is_cv_gap = train_metrics["train_accuracy"] - train_metrics["cv_mean_accuracy"]
    n_total_trades = n_trades_unf

    assessments = []
    flags = []

    # Check 1: IS-CV gap
    if is_cv_gap > 0.20:
        flags.append(f"HIGH IS-CV gap ({is_cv_gap:.2f}) → RF overfitting on training set")
    else:
        assessments.append(f"IS-CV gap acceptable ({is_cv_gap:.2f} < 0.20)")

    # Check 2: OOS precision
    if oos_precision >= 0.55:
        assessments.append(f"OOS precision {oos_precision:.3f} >= 0.55 threshold (López edge condition)")
    else:
        flags.append(f"OOS precision {oos_precision:.3f} < 0.55 — below López edge threshold")

    # Check 3: DSR
    if dsr_flt >= 0.60:
        assessments.append(f"Filtered DSR {dsr_flt:.3f} >= 0.60 (acceptable per López)")
    elif dsr_flt >= 0.50:
        flags.append(f"Filtered DSR {dsr_flt:.3f} in [0.50, 0.60] — marginal, more data needed")
    else:
        flags.append(f"Filtered DSR {dsr_flt:.3f} < 0.50 — strategy may be random")

    # Check 4: Sample size
    if n_total_trades < 30:
        flags.append(f"Only {n_total_trades} OOS trades — insufficient for statistical significance")
    else:
        assessments.append(f"{n_total_trades} OOS trades — sufficient for basic statistics")

    # Check 5: Trades filtered severely
    if n_trades_flt == 0:
        flags.append("Filter removed ALL trades — threshold too high or model broken")
    elif pct_kept < 20:
        flags.append(f"Filter kept only {pct_kept:.1f}% of trades — may cause execution issues")
    elif 30 <= pct_kept <= 70:
        assessments.append(f"Filter kept {pct_kept:.1f}% of trades (30-70% target range)")

    # Check 6: Win rate vs claim
    if wr_flt >= 0.55:
        assessments.append(f"Filtered win rate {wr_flt:.1%} meets ≥55% hypothesis target")
    else:
        flags.append(f"Filtered win rate {wr_flt:.1%} < 55% — hypothesis not met")

    if assessments:
        print("  Evidence FOR real edge:")
        for a in assessments:
            print(f"    [+] {a}")

    if flags:
        print("  Evidence AGAINST (caution flags):")
        for f in flags:
            print(f"    [-] {f}")

    # Final verdict
    print()
    n_flags = len(flags)
    n_ok = len(assessments)
    if n_flags == 0 and improved:
        conclusion = "STRONG: ML filter shows real uplift with statistically sound evidence."
    elif n_flags <= 1 and improved:
        conclusion = "MODERATE: ML filter shows uplift but with minor caveats."
    elif not improved:
        conclusion = (
            "REJECT: ML filter did not improve performance. "
            "Possible causes: insufficient signal count, low S/N ratio in features, "
            "or engulfing signals are already near-random at this dataset size."
        )
    else:
        conclusion = (
            f"CAUTION: {n_flags} red flags detected. "
            "Results may be curve-fitted. Do not deploy without more data."
        )

    print(f"  CONCLUSION: {conclusion}")
    print()
    print("  Note: López methodology requires DSR > 0.6 AND OOS precision > 0.55")
    print("  for a meta-label filter to be considered production-ready.")
    print("  Marginal DSR (0.38 baseline) needs substantial improvement to cross 0.6.")

    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n[INTERRUPTED]")
        sys.exit(1)
    except Exception as exc:
        print(f"\n[FATAL ERROR] {type(exc).__name__}: {exc}")
        traceback.print_exc()
        sys.exit(2)
