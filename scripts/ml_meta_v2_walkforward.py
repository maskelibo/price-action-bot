"""ML Meta-Labeling v2 — Multi-TF + Alt-Data Continuous (HYP-2026-05-17).

Pre-reg: memory/researcher/hypotheses/2026-05-17-feature-space-v2.md

ML v1 + 5 yeni feature: atr_pct_4h, rsi_14_4h, vol_z_1h, funding_z_24h, fng_value.
Aynı RF konfigurasyonu (n=200, max_depth=6, min_leaf=5, threshold=0.55).
6 pencere walk-forward + shuffle null (200 iter) + bootstrap CI (2000 iter).

Output: reports/research/ml_meta_v2_results.txt
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import time
import warnings
from pathlib import Path

os.environ["PA_LOG_QUIET"] = "1"
warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from price_action.ml.meta_labeling import train_rf, predict_filter
from price_action.ml.features_v2 import build_v2_features, load_alt_data, load_mtf_caches

# ML v1 functions reuse
from scripts.ml_meta_labeling_walkforward import (
    CONFIG as CONFIG_V1,
    load_trades,
    load_ohlcv,
    build_full_feature_matrix,
    get_windows,
    compute_trade_metrics,
    bootstrap_ci,
    shuffle_null_test as shuffle_null_v1,
)

CONFIG = dict(CONFIG_V1)
CONFIG["version"] = "v2"
CONFIG["new_features"] = [
    "atr_pct_4h", "rsi_14_4h", "vol_z_1h", "funding_z_24h", "fng_value"
]

REPORT_OUT = ROOT / "reports" / "research" / "ml_meta_v2_results.txt"


def stable_hash(obj) -> str:
    s = json.dumps(obj, sort_keys=True, default=str)
    return hashlib.sha256(s.encode("utf-8")).hexdigest()[:16]


def main() -> None:
    REPORT_OUT.parent.mkdir(parents=True, exist_ok=True)
    out_lines: list[str] = []

    def w(line: str = "") -> None:
        print(line)
        out_lines.append(line)

    t0 = time.time()
    w("=" * 78)
    w("ML META-LABELING v2 — MTF + ALT-DATA CONTINUOUS")
    w("=" * 78)
    w(f"Pre-reg: memory/researcher/hypotheses/2026-05-17-feature-space-v2.md")
    w(f"Generated: {pd.Timestamp.utcnow().isoformat()}")
    w(f"Config hash: {stable_hash(CONFIG)}")
    w("")

    # 1) Data load
    w("--- 1) DATA LOAD ---")
    df_trades = load_trades()
    ohlcv = load_ohlcv()
    cache_4h, cache_1h = load_mtf_caches(ROOT)
    df_funding, df_fng = load_alt_data(ROOT)
    w(f"Trade pool: {len(df_trades)}")
    w(f"OHLCV (1d): {len(ohlcv)} sym")
    w(f"4h cache: {len(cache_4h)} sym, {sum(len(v) for v in cache_4h.values())} bar")
    w(f"1h cache: {len(cache_1h)} sym, {sum(len(v) for v in cache_1h.values())} bar")
    w(f"Funding: {len(df_funding)} event, {df_funding['ts'].min()} -> {df_funding['ts'].max()}")
    w(f"FnG: {len(df_fng)} day, {df_fng['ts'].min()} -> {df_fng['ts'].max()}")

    # 2) Feature engineering — v1 (13) + v2 (5)
    w("\n--- 2) FEATURE ENGINEERING ---")
    t1 = time.time()
    df_feat_v1 = build_full_feature_matrix(df_trades, ohlcv)
    common_idx = df_feat_v1.index.intersection(df_trades.index)
    df_feat_v1 = df_feat_v1.loc[common_idx]
    df_aligned = df_trades.loc[common_idx].copy()
    w(f"v1 feature matrix: {df_feat_v1.shape}  ({time.time()-t1:.1f}s)")

    t2 = time.time()
    trades_dicts = df_aligned.to_dict("records")
    df_feat_v2_new = build_v2_features(trades_dicts, cache_4h, cache_1h, df_funding, df_fng)
    df_feat_v2_new.index = df_aligned.index
    w(f"v2 yeni 5 feature: {df_feat_v2_new.shape}  ({time.time()-t2:.1f}s)")

    # NaN report
    nan_pct = df_feat_v2_new.isna().mean() * 100
    w("Yeni feature NaN%:")
    for c, pct in nan_pct.items():
        w(f"  {c}: {pct:.2f}%")

    # Combine
    df_feat = pd.concat([df_feat_v1, df_feat_v2_new], axis=1)
    feat_cols_v1 = [c for c in df_feat_v1.columns if c not in ("direction", "symbol", "signal_ts", "signal_ts_utc")]
    feat_cols_v2 = list(df_feat_v2_new.columns)
    feat_cols = feat_cols_v1 + feat_cols_v2
    w(f"Toplam feature ({len(feat_cols)}): {len(feat_cols_v1)} v1 + {len(feat_cols_v2)} v2")

    # 3) Windows
    w("\n--- 3) WALK-FORWARD WINDOWS ---")
    windows = get_windows(
        df_aligned,
        train_y=CONFIG["walk_forward"]["train_y"],
        oos_mo=CONFIG["walk_forward"]["oos_mo"],
        step_mo=CONFIG["walk_forward"]["step_mo"],
    )
    w(f"Windows: {len(windows)}")

    # 4) Per-window walk-forward
    w("\n--- 4) PER-WINDOW WALK-FORWARD ---")
    results: list[dict] = []

    for ww in windows:
        w(f"\nW{ww['idx']}/{len(windows)}: training...")
        tw = time.time()

        train_mask = (df_aligned["entry_ts"] >= ww["train_start"]) & (df_aligned["entry_ts"] < ww["train_end"])
        oos_mask = (df_aligned["entry_ts"] >= ww["train_end"]) & (df_aligned["entry_ts"] < ww["oos_end"])
        train_idx = df_aligned[train_mask].index
        oos_idx = df_aligned[oos_mask].index

        # Median imputation (train-only)
        X_train_raw = df_feat.loc[train_idx, feat_cols].astype(float)
        train_medians = X_train_raw.median()
        X_train = X_train_raw.fillna(train_medians).replace([np.inf, -np.inf], 0.0)
        y_train = df_aligned.loc[train_idx, "y"]

        X_oos_raw = df_feat.loc[oos_idx, feat_cols].astype(float)
        X_oos = X_oos_raw.fillna(train_medians).replace([np.inf, -np.inf], 0.0)
        R_oos = df_aligned.loc[oos_idx, "R"].values

        if len(X_train) < 100 or len(X_oos) < 30:
            w(f"  SKIP - n_train={len(X_train)} n_oos={len(X_oos)}")
            continue

        ldf = pd.DataFrame({"t0": np.arange(len(X_train)), "t1": np.arange(len(X_train)) + 1})

        clf, metrics = train_rf(
            X_train, y_train, labels_df=ldf,
            cv=CONFIG["purged_kfold"]["n_folds"],
            n_estimators=CONFIG["n_estimators"],
            max_depth=CONFIG["max_depth"],
            min_samples_leaf=CONFIG["min_samples_leaf"],
            random_state=CONFIG["random_state"],
            embargo_bars=CONFIG["purged_kfold"]["embargo_bars"],
        )

        mask_oos = predict_filter(clf, X_oos, threshold=CONFIG["threshold"], feature_names=feat_cols)
        ml_R = R_oos[mask_oos.values]
        baseline_R = R_oos

        ml_metrics = compute_trade_metrics(ml_R)
        bl_metrics = compute_trade_metrics(baseline_R)
        sharpe_alpha = ml_metrics["sharpe"] - bl_metrics["sharpe"]

        # Shuffle null
        w(f"  shuffle null ({CONFIG['shuffle_iters']} iter)...")
        ts_shuf = time.time()
        null_dist = shuffle_null_v1(
            X_train, y_train, X_oos, R_oos,
            baseline_sharpe=bl_metrics["sharpe"],
            n_iter=CONFIG["shuffle_iters"],
            threshold=CONFIG["threshold"],
            rng_seed=42 + ww["idx"],
        )
        p_shuf = float((null_dist >= sharpe_alpha).mean())
        w(f"  shuffle done ({time.time()-ts_shuf:.1f}s)")

        # v2 yeni feature importance ratio
        importance = metrics.get("feature_importance", {})
        v2_importance_sum = sum(importance.get(c, 0) for c in feat_cols_v2)

        rec = {
            "idx": ww["idx"],
            "n_train": len(X_train),
            "n_oos": len(X_oos),
            "n_taken": int(mask_oos.sum()),
            "survival_rate": float(mask_oos.mean()),
            "train_acc": metrics["train_accuracy"],
            "cv_acc": metrics["cv_mean_accuracy"],
            "cv_auc": metrics["cv_mean_auc"],
            "overfit_gap": metrics["train_accuracy"] - metrics["cv_mean_accuracy"],
            "ml_sharpe": ml_metrics["sharpe"],
            "ml_ret": ml_metrics["ret"],
            "ml_dd": ml_metrics["dd"],
            "bl_sharpe": bl_metrics["sharpe"],
            "bl_ret": bl_metrics["ret"],
            "bl_dd": bl_metrics["dd"],
            "sharpe_alpha": sharpe_alpha,
            "p_shuffle": p_shuf,
            "v2_importance_sum": v2_importance_sum,
            "feature_importance": importance,
        }
        results.append(rec)
        w(f"  W{ww['idx']}: n_taken={rec['n_taken']}/{len(X_oos)} ({rec['survival_rate']*100:.1f}%) "
          f"ml_sh={rec['ml_sharpe']:+.3f} bl_sh={rec['bl_sharpe']:+.3f} "
          f"alpha={rec['sharpe_alpha']:+.3f} p={rec['p_shuffle']:.3f} "
          f"cv_auc={rec['cv_auc']:.3f} v2_imp={v2_importance_sum:.3f} "
          f"({time.time()-tw:.1f}s)")

    # 5) Aggregate + gates
    w("\n--- 5) AGGREGATE + GATES ---")
    if not results:
        w("HATA: Hicbir pencere calismadi.")
        REPORT_OUT.write_text("\n".join(out_lines), encoding="utf-8")
        return

    df_res = pd.DataFrame(results)
    mean_alpha = float(df_res["sharpe_alpha"].mean())
    mean_cv_auc = float(df_res["cv_auc"].mean())
    mean_overfit = float(df_res["overfit_gap"].mean())
    mean_survival = float(df_res["survival_rate"].mean())
    mean_v2_imp = float(df_res["v2_importance_sum"].mean())

    lo, hi = bootstrap_ci(df_res["sharpe_alpha"].values, n_iter=CONFIG["bootstrap_iters"])

    alpha_adj = 0.05 / len(results)
    n_bonferroni = int((df_res["p_shuffle"] < alpha_adj).sum())
    n_shuffle = int((df_res["p_shuffle"] < 0.05).sum())

    w(f"\nMean Sharpe alpha:           {mean_alpha:+.4f}  (target >=+0.15)")
    w(f"Bootstrap CI(95%):           [{lo:+.4f}, {hi:+.4f}]  (target low > 0)")
    w(f"Mean CV AUC:                 {mean_cv_auc:.4f}  (target >=0.55)")
    w(f"Mean overfit gap:            {mean_overfit:+.4f}  (target <0.15)")
    w(f"Mean survival rate:          {mean_survival:.4f}  (target 0.20-0.95)")
    w(f"Shuffle p<0.05:              {n_shuffle}/{len(results)}  (target >=5/6)")
    w(f"Bonferroni p<{alpha_adj:.5f}:    {n_bonferroni}/{len(results)}  (target >=3/6)")
    w(f"Mean v2 importance sum:      {mean_v2_imp:.4f}  (target >=0.25)")

    # Per-window detail
    w("\nPer-window detail:")
    w(f"  {'W':>2s} {'taken':>5s} {'cv_auc':>6s} {'gap':>6s} "
      f"{'ml_sh':>7s} {'bl_sh':>7s} {'alpha':>7s} {'p_sh':>6s} {'v2_imp':>6s}")
    for r in results:
        w(f"  {r['idx']:>2d} {r['n_taken']:>5d} "
          f"{r['cv_auc']:>6.3f} {r['overfit_gap']:>+6.3f} "
          f"{r['ml_sharpe']:>+7.3f} {r['bl_sharpe']:>+7.3f} {r['sharpe_alpha']:>+7.3f} "
          f"{r['p_shuffle']:>6.3f} {r['v2_importance_sum']:>6.3f}")

    # ML v1 comparison
    w("\nv1 vs v2 karsilastirma:")
    v1_alpha = 0.8099  # from prev result
    v1_auc = 0.5274
    w(f"  v1: mean_alpha={v1_alpha:+.4f}, mean_auc={v1_auc:.4f}")
    w(f"  v2: mean_alpha={mean_alpha:+.4f}, mean_auc={mean_cv_auc:.4f}")
    delta_alpha = mean_alpha - v1_alpha
    delta_auc = mean_cv_auc - v1_auc
    w(f"  Delta: alpha={delta_alpha:+.4f}, auc={delta_auc:+.4f}")

    # 6) HARD gate karari
    w("\n--- 6) HARD GATE KARARI ---")
    gates_failed: list[str] = []
    if mean_alpha < 0.15:
        gates_failed.append(f"NH1 mean Sharpe alpha {mean_alpha:+.4f} < +0.15")
    if lo <= 0:
        gates_failed.append(f"NH2 bootstrap CI low {lo:+.4f} <= 0")
    if n_shuffle < 5:
        gates_failed.append(f"NH3 shuffle pass {n_shuffle}/{len(results)} < 5/6")
    if n_bonferroni < 3:
        gates_failed.append(f"NH4 Bonferroni pass {n_bonferroni}/{len(results)} < 3/6")
    if mean_cv_auc < 0.55:
        gates_failed.append(f"NH5 mean CV AUC {mean_cv_auc:.4f} < 0.55")
    if mean_overfit > 0.15:
        gates_failed.append(f"NH6 overfit gap {mean_overfit:+.4f} > 0.15")
    if mean_survival < 0.20 or mean_survival > 0.95:
        gates_failed.append(f"NH7 survival rate {mean_survival:.4f} out of [0.20, 0.95]")
    if mean_v2_imp < 0.25:
        gates_failed.append(f"NH8 v2 importance sum {mean_v2_imp:.4f} < 0.25")

    if gates_failed:
        w(f"\nGATES FAILED ({len(gates_failed)}/8):")
        for g in gates_failed:
            w(f"  [X] {g}")
        verdict = "RED"
    else:
        w("\nTUM GATES PASS")
        verdict = "PASS"

    w(f"\nKARAR: {verdict}")
    w(f"\nElapsed: {time.time()-t0:.1f}s")

    # JSON dump
    json_path = REPORT_OUT.with_suffix(".json")
    # Sanitize per-window for JSON (drop full feature_importance)
    pw_export = []
    for r in results:
        rr = {k: v for k, v in r.items() if k != "feature_importance"}
        pw_export.append(rr)
    json_path.write_text(json.dumps({
        "config": CONFIG,
        "verdict": verdict,
        "aggregates": {
            "mean_sharpe_alpha": mean_alpha,
            "ci_lo": lo, "ci_hi": hi,
            "mean_cv_auc": mean_cv_auc,
            "mean_overfit_gap": mean_overfit,
            "mean_survival_rate": mean_survival,
            "shuffle_pass": n_shuffle,
            "bonferroni_pass": n_bonferroni,
            "alpha_adj": alpha_adj,
            "n_windows": len(results),
            "v2_mean_importance_sum": mean_v2_imp,
            "v1_baseline_alpha": v1_alpha,
            "v1_baseline_auc": v1_auc,
            "delta_alpha": delta_alpha,
            "delta_auc": delta_auc,
        },
        "gates_failed": gates_failed,
        "per_window": pw_export,
    }, indent=2, default=str), encoding="utf-8")

    REPORT_OUT.write_text("\n".join(out_lines), encoding="utf-8")
    w(f"\nRapor: {REPORT_OUT}")
    w(f"JSON:  {json_path}")


if __name__ == "__main__":
    main()
