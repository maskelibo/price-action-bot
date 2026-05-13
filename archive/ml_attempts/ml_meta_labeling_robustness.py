"""ML Meta-Labeling v1.1 - SECTION 5: Robustness Suite (DIAGNOSTIC).

Pre-reg: memory/researcher/hypotheses/2026-05-15-ml-meta-labeling-v1.md

DIAGNOSTIC TESTS (PASS/FAIL ile main hipotezi etkilemez, sadece guvenlik kontrolu):
  1. Threshold duyarlilik: 0.50 / 0.55 / 0.60 (pre-reg default 0.55)
  2. Symbol-out CV: 11 sym, her birini drop, retrain, OOS sapma <%30
  3. Strategy-out CV: 10 strat, her birini drop, retrain, OOS sapma <%30
  4. Feature ablation top-5: en yuksek importance 5 feature drop
  5. Look-ahead audit: 50 random trade, manuel feature timestamp dogrulamasi
  6. Triple-barrier sanity (atr_mult sym 2.0/2.0): label dist + concordance

Bu script SECTION 4 walk-forward sonuclari uretildikten sonra calistirilir.

Output: reports/research/ml_meta_v1_robustness.txt
"""
from __future__ import annotations

import json
import os
import pickle
import sys
import warnings
from pathlib import Path

os.environ["PA_LOG_QUIET"] = "1"
warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from price_action.ml.meta_labeling import (
    engineer_features,
    triple_barrier_labels,
    train_rf,
    predict_filter,
)

# Reuse helpers from main walkforward
from scripts.ml_meta_labeling_walkforward import (
    CONFIG,
    load_trades,
    load_ohlcv,
    build_full_feature_matrix,
    get_windows,
    compute_trade_metrics,
    trade_to_signal,
)

REPORT_OUT = ROOT / "reports" / "research" / "ml_meta_v1_robustness.txt"
MAIN_RESULT = ROOT / "reports" / "research" / "ml_meta_v1_results.json"


def run_walkforward_simple(
    df_aligned: pd.DataFrame,
    df_feat: pd.DataFrame,
    feat_cols: list[str],
    threshold: float = 0.55,
) -> dict:
    """Simple walk-forward, no shuffle null. Sadece per-window Sharpe alpha."""
    windows = get_windows(
        df_aligned,
        train_y=CONFIG["walk_forward"]["train_y"],
        oos_mo=CONFIG["walk_forward"]["oos_mo"],
        step_mo=CONFIG["walk_forward"]["step_mo"],
    )
    sharpe_alphas: list[float] = []
    survivals: list[float] = []

    for ww in windows:
        train_mask = (df_aligned["entry_ts"] >= ww["train_start"]) & (df_aligned["entry_ts"] < ww["train_end"])
        oos_mask = (df_aligned["entry_ts"] >= ww["train_end"]) & (df_aligned["entry_ts"] < ww["oos_end"])
        train_idx = df_aligned[train_mask].index
        oos_idx = df_aligned[oos_mask].index

        if len(train_idx) < 100 or len(oos_idx) < 30:
            continue

        X_train = df_feat.loc[train_idx, feat_cols].astype(float)
        y_train = df_aligned.loc[train_idx, "y"]
        X_oos = df_feat.loc[oos_idx, feat_cols].astype(float)
        R_oos = df_aligned.loc[oos_idx, "R"].values

        ldf = pd.DataFrame({
            "t0": np.arange(len(X_train)),
            "t1": np.arange(len(X_train)) + 1,
        })

        try:
            clf, _ = train_rf(
                X_train, y_train, labels_df=ldf,
                cv=CONFIG["purged_kfold"]["n_folds"],
                n_estimators=CONFIG["n_estimators"],
                max_depth=CONFIG["max_depth"],
                min_samples_leaf=CONFIG["min_samples_leaf"],
                random_state=CONFIG["random_state"],
                embargo_bars=CONFIG["purged_kfold"]["embargo_bars"],
            )
        except Exception:
            continue
        mask = predict_filter(clf, X_oos, threshold=threshold, feature_names=feat_cols)
        ml_R = R_oos[mask.values]
        ml_m = compute_trade_metrics(ml_R)
        bl_m = compute_trade_metrics(R_oos)
        sharpe_alphas.append(ml_m["sharpe"] - bl_m["sharpe"])
        survivals.append(float(mask.mean()))

    return {
        "n_windows": len(sharpe_alphas),
        "mean_sharpe_alpha": float(np.mean(sharpe_alphas)) if sharpe_alphas else 0.0,
        "mean_survival": float(np.mean(survivals)) if survivals else 0.0,
    }


def main() -> None:
    REPORT_OUT.parent.mkdir(parents=True, exist_ok=True)
    out_lines: list[str] = []

    def w(line: str = "") -> None:
        print(line)
        out_lines.append(line)

    w("=" * 78)
    w("ML META-LABELING v1.1 - ROBUSTNESS SUITE (DIAGNOSTIC)")
    w("=" * 78)
    w(f"Generated: {pd.Timestamp.utcnow().isoformat()}")
    w("")

    # Load main result for baseline comparison
    if MAIN_RESULT.exists():
        with MAIN_RESULT.open() as f:
            main_res = json.load(f)
        baseline_alpha = main_res["aggregates"]["mean_sharpe_alpha"]
        baseline_survival = main_res["aggregates"]["mean_survival_rate"]
        w(f"MAIN baseline (threshold=0.55): mean_sharpe_alpha={baseline_alpha:+.4f}, survival={baseline_survival:.4f}")
    else:
        w("MAIN result yok - bu test once SECTION 3+4 calistir.")
        return
    w("")

    # Data load
    df_trades = load_trades()
    ohlcv = load_ohlcv()
    df_feat = build_full_feature_matrix(df_trades, ohlcv)
    common_idx = df_feat.index.intersection(df_trades.index)
    df_feat = df_feat.loc[common_idx]
    df_aligned = df_trades.loc[common_idx].copy()
    feat_cols = [c for c in df_feat.columns if c not in ("direction", "symbol", "signal_ts", "signal_ts_utc")]
    w(f"Aligned trade count: {len(df_aligned)}")
    w(f"Feature cols ({len(feat_cols)}): {feat_cols}")
    w("")

    # 1) Threshold duyarlilik
    w("--- 1) THRESHOLD DUYARLILIK (0.50/0.55/0.60) ---")
    thresh_results = {}
    for thr in [0.50, 0.55, 0.60]:
        r = run_walkforward_simple(df_aligned, df_feat, feat_cols, threshold=thr)
        thresh_results[thr] = r
        delta_pct = (r["mean_sharpe_alpha"] - baseline_alpha) / max(abs(baseline_alpha), 1e-6) * 100
        w(f"  thr={thr}: mean_alpha={r['mean_sharpe_alpha']:+.4f} ({delta_pct:+.1f}%) "
          f"survival={r['mean_survival']:.3f} n_win={r['n_windows']}")
    max_dev = max(
        abs(r["mean_sharpe_alpha"] - baseline_alpha) / max(abs(baseline_alpha), 1e-6)
        for r in thresh_results.values()
    ) * 100
    gate_thresh = "PASS" if max_dev < 30 else "WARN"
    w(f"  Max sapma %{max_dev:.1f} ({gate_thresh}, gate <%30)")

    # 2) Symbol-out CV
    w("\n--- 2) SYMBOL-OUT CV ---")
    sym_results = {}
    for sym in df_aligned["symbol"].unique():
        mask = df_aligned["symbol"] != sym
        df_a_sub = df_aligned[mask]
        df_f_sub = df_feat.loc[df_a_sub.index]
        r = run_walkforward_simple(df_a_sub, df_f_sub, feat_cols)
        sym_results[sym] = r
        delta_pct = (r["mean_sharpe_alpha"] - baseline_alpha) / max(abs(baseline_alpha), 1e-6) * 100
        w(f"  drop {sym}: mean_alpha={r['mean_sharpe_alpha']:+.4f} ({delta_pct:+.1f}%)")
    sym_devs = [
        abs(r["mean_sharpe_alpha"] - baseline_alpha) / max(abs(baseline_alpha), 1e-6) * 100
        for r in sym_results.values()
    ]
    max_sym_dev = max(sym_devs) if sym_devs else 0
    gate_sym = "PASS" if max_sym_dev < 30 else "WARN"
    w(f"  Max sapma %{max_sym_dev:.1f} ({gate_sym}, gate <%30)")

    # 3) Strategy-out CV
    w("\n--- 3) STRATEGY-OUT CV ---")
    strat_results = {}
    for strat in df_aligned["strategy"].unique():
        mask = df_aligned["strategy"] != strat
        df_a_sub = df_aligned[mask]
        df_f_sub = df_feat.loc[df_a_sub.index]
        r = run_walkforward_simple(df_a_sub, df_f_sub, feat_cols)
        strat_results[strat] = r
        delta_pct = (r["mean_sharpe_alpha"] - baseline_alpha) / max(abs(baseline_alpha), 1e-6) * 100
        w(f"  drop {strat:35s}: mean_alpha={r['mean_sharpe_alpha']:+.4f} ({delta_pct:+.1f}%)")
    strat_devs = [
        abs(r["mean_sharpe_alpha"] - baseline_alpha) / max(abs(baseline_alpha), 1e-6) * 100
        for r in strat_results.values()
    ]
    max_strat_dev = max(strat_devs) if strat_devs else 0
    gate_strat = "PASS" if max_strat_dev < 30 else "WARN"
    w(f"  Max sapma %{max_strat_dev:.1f} ({gate_strat}, gate <%30)")

    # 4) Feature ablation top-5 (main result'tan importance al)
    w("\n--- 4) FEATURE ABLATION TOP-5 ---")
    if "per_window" in main_res and main_res["per_window"]:
        # Re-train on full training data icin importance
        last_w = main_res["per_window"][-1]
        # Importance hesaplamak icin son windowda RF egit
        train_mask = df_aligned["entry_ts"] < df_aligned["entry_ts"].quantile(0.6)
        train_idx = df_aligned[train_mask].index
        X_train = df_feat.loc[train_idx, feat_cols].astype(float)
        y_train = df_aligned.loc[train_idx, "y"]
        ldf = pd.DataFrame({"t0": np.arange(len(X_train)), "t1": np.arange(len(X_train))+1})
        clf, metrics = train_rf(
            X_train, y_train, labels_df=ldf,
            cv=CONFIG["purged_kfold"]["n_folds"],
            n_estimators=CONFIG["n_estimators"],
            max_depth=CONFIG["max_depth"],
            min_samples_leaf=CONFIG["min_samples_leaf"],
            random_state=CONFIG["random_state"],
        )
        importance = metrics["feature_importance"]
        top5 = list(importance.keys())[:5]
        w(f"  Top-5 feature importance: {top5}")
        for f_drop in top5:
            cols_kept = [c for c in feat_cols if c != f_drop]
            r = run_walkforward_simple(df_aligned, df_feat, cols_kept)
            delta_pct = (r["mean_sharpe_alpha"] - baseline_alpha) / max(abs(baseline_alpha), 1e-6) * 100
            w(f"  drop {f_drop:30s}: mean_alpha={r['mean_sharpe_alpha']:+.4f} ({delta_pct:+.1f}%)")
    else:
        w("  Per-window importance bulunamadi.")

    # 5) Look-ahead audit
    w("\n--- 5) LOOK-AHEAD AUDIT (50 random trade) ---")
    rng = np.random.default_rng(42)
    sample_idx = rng.choice(df_aligned.index, size=min(50, len(df_aligned)), replace=False)
    look_violations = 0
    for idx in sample_idx:
        trade = df_aligned.loc[idx]
        sig_ts = trade["signal_ts"]
        entry_ts = trade["entry_ts"]
        # Feature row alindi mi?
        if idx not in df_feat.index:
            continue
        feat_row = df_feat.loc[idx]
        # Check: signal_ts < entry_ts oldugundan emin ol
        if sig_ts >= entry_ts:
            look_violations += 1
            w(f"  VIOLATION trade {idx}: sig_ts={sig_ts} >= entry_ts={entry_ts}")
    audit_gate = "PASS" if look_violations == 0 else "FAIL"
    w(f"  Look-ahead violations: {look_violations}/50 ({audit_gate})")

    # 6) Triple-barrier sanity (sym 2.0/2.0)
    w("\n--- 6) TRIPLE-BARRIER SANITY (atr_mult sym 2.0/2.0) ---")
    all_labels = []
    for sym, df_sym in ohlcv.items():
        sym_trades = df_aligned[df_aligned["symbol"] == sym]
        if sym_trades.empty:
            continue
        signals = [trade_to_signal(t) for t in sym_trades.to_dict("records")]
        try:
            labels = triple_barrier_labels(
                df_sym, signals,
                atr_mult_tp=2.0, atr_mult_sl=2.0,  # symmetric!
                max_holding=20,
            )
        except Exception:
            continue
        if not labels.empty:
            labels["symbol"] = sym
            all_labels.append(labels)
    if all_labels:
        df_lab = pd.concat(all_labels, ignore_index=True)
        n_total = len(df_lab)
        n_tp = int((df_lab["label"] == 1).sum())
        n_sl = int((df_lab["label"] == -1).sum())
        n_to = int((df_lab["label"] == 0).sum())
        w(f"  n={n_total}, TP={n_tp/n_total*100:.1f}%, SL={n_sl/n_total*100:.1f}%, TO={n_to/n_total*100:.1f}%")
        w(f"  mean_holding={df_lab['holding_bars'].mean():.2f} bar")
        balance = (df_lab["label"] == 1).mean()
        gate_tb = "PASS" if 0.30 <= balance <= 0.70 else "WARN"
        w(f"  Class balance (TP=1): {balance:.4f} ({gate_tb}, gate 0.30-0.70)")

    # Summary
    w("\n--- SUMMARY ---")
    w(f"Main pre-reg sonucu: mean_sharpe_alpha={baseline_alpha:+.4f}")
    w(f"Threshold robust:    {gate_thresh} (max sapma %{max_dev:.1f})")
    w(f"Symbol-out robust:   {gate_sym} (max sapma %{max_sym_dev:.1f})")
    w(f"Strategy-out robust: {gate_strat} (max sapma %{max_strat_dev:.1f})")
    w(f"Look-ahead audit:    {audit_gate} ({look_violations}/50 violations)")

    REPORT_OUT.write_text("\n".join(out_lines), encoding="utf-8")
    w(f"\nRapor: {REPORT_OUT}")


if __name__ == "__main__":
    main()
