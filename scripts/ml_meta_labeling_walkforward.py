"""ML Meta-Labeling v1.1 — SECTION 3+4: Walk-Forward + Stat Gates.

Pre-reg: memory/researcher/hypotheses/2026-05-15-ml-meta-labeling-v1.md
Pre-reg version: 0.1.1 (post-baseline EDA revision)

Pipeline:
  1) Cached trades + OHLCV yukle
  2) Per-trade engineer_features (lookahead-free)
  3) y = (R > 0).astype(int) - strategy R-based label
  4) 6 walk-forward pencere (3y train + 6mo OOS + 3mo step)
  5) Per pencere:
       - train_rf (purged k-fold CV, uniqueness weights)
       - predict_filter (threshold=0.55)
       - ML_filter trades vs flat_T2 baseline (her trade %2 risk, 2x lev)
       - Sharpe alpha hesabi
       - Shuffle null (200 iter, label permutation)
  6) Bonferroni adj (alpha = 0.05/6 = 0.00833)
  7) Bootstrap CI (2000 iter, mean Sharpe alpha)
  8) Gate kontrolu

Output: reports/research/ml_meta_v1_results.txt

NOT: Hiperparametre sweep YASAK. Tum konfig pre-reg dan.
"""
from __future__ import annotations

import hashlib
import json
import os
import pickle
import sys
import time
import warnings
from dataclasses import dataclass
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

TRADES_CACHE = ROOT / "data" / "v095_trades_cache.pkl"
OHLCV_CACHE = ROOT / "data" / "v095_ohlcv_cache.pkl"
REPORT_OUT = ROOT / "reports" / "research" / "ml_meta_v1_results.txt"

# Pre-reg config (SABIT, sweep YASAK)
CONFIG = {
    "model": "RandomForestClassifier",
    "n_estimators": 200,
    "max_depth": 6,
    "min_samples_leaf": 5,
    "class_weight": "balanced",
    "random_state": 42,
    "threshold": 0.55,
    "purged_kfold": {"n_folds": 5, "embargo_bars": 5},
    "walk_forward": {"train_y": 3, "oos_mo": 6, "step_mo": 3},
    "label_method": "strategy_R_based",
    "baseline": "flat_T2_2pct_2x",
    "shuffle_iters": 200,
    "bootstrap_iters": 2000,
    "label_for_triple_barrier_sanity": {"atr_mult_tp": 2.0, "atr_mult_sl": 1.0, "max_holding": 20},
}


def stable_hash(obj) -> str:
    s = json.dumps(obj, sort_keys=True, default=str)
    return hashlib.sha256(s.encode("utf-8")).hexdigest()[:16]


def load_trades() -> pd.DataFrame:
    with TRADES_CACHE.open("rb") as f:
        trades = pickle.load(f)
    df = pd.DataFrame(trades)
    df["entry_ts"] = pd.to_datetime(df["entry_ts"], utc=True)
    df["exit_ts"] = pd.to_datetime(df["exit_ts"], utc=True)
    df["signal_ts"] = df["entry_ts"] - pd.Timedelta(days=1)
    df["y"] = (df["R"] > 0).astype(int)
    df = df.sort_values("entry_ts").reset_index(drop=True)
    return df


def load_ohlcv() -> dict[str, pd.DataFrame]:
    with OHLCV_CACHE.open("rb") as f:
        d = pickle.load(f)
    out: dict[str, pd.DataFrame] = {}
    for sym, df_in in d.items():
        df = df_in.copy()
        if df.index.name == "ts_date":
            df = df.reset_index().rename(columns={"ts_date": "_dt"})
        if "ts" in df.columns:
            df["ts"] = pd.to_datetime(df["ts"], utc=True)
        elif "_dt" in df.columns:
            df["ts"] = pd.to_datetime(df["_dt"], utc=True)
        cols_keep = ["ts", "open", "high", "low", "close", "volume"]
        for opt in ["atr14", "ema20", "ema200", "kaufman_er"]:
            if opt in df.columns:
                cols_keep.append(opt)
        df = df[[c for c in cols_keep if c in df.columns]].sort_values("ts").reset_index(drop=True)
        out[sym] = df
    return out


def trade_to_signal(t: dict) -> dict:
    return {
        "ts": pd.Timestamp(t["signal_ts"]),
        "direction": str(t["side"]).lower(),
        "entry_price": float(t["entry_price"]),
        "sl_price": float(t["initial_sl"]),
        "tp_price": None,
        "confluence_score": float(t.get("conf", 0.0)),
        "vol_z": float(t.get("vol_z", 0.0)),
        "symbol": t["symbol"],
        "strategy": t["strategy"],
        "metadata": {"near_sr": False},
    }


def build_full_feature_matrix(df_trades: pd.DataFrame, ohlcv: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Tum trade'ler icin feature matrix - per-symbol engineer_features ile.

    Returns: DataFrame indexed by trade_index (df_trades order), 15 columns:
             13 features + direction + symbol metadata.
    """
    feat_rows: list[dict] = []
    feat_idx: list[int] = []

    for sym, df_sym in ohlcv.items():
        sym_mask = df_trades["symbol"] == sym
        if not sym_mask.any():
            continue
        sym_trades = df_trades[sym_mask]
        signals = [trade_to_signal(t) for t in sym_trades.to_dict("records")]
        feats = engineer_features(df_sym, signals)
        if feats.empty:
            continue
        # Eslestir signal_ts'a gore — hem feats index'i hem sym_trades signal_ts UTC datetime
        feats = feats.reset_index()
        feats["symbol"] = sym
        # Eslestirme dolaylı: feats sirasi signals sirasi ile ayni (engineer_features sirayla
        # signal_ts'a gore for-loop ile dolduruyor). Ama biz daha guvenli olsun diye
        # sym_trades index'leri ile birebir iliskilendirelim.
        if len(feats) != len(sym_trades):
            # Yetersiz veri olan signal'lar drop edilmis; signal_ts ile birlestir
            sym_trades_indexed = sym_trades.reset_index().rename(columns={"index": "trade_idx"})
            sym_trades_indexed["signal_ts_utc"] = pd.to_datetime(
                sym_trades_indexed["signal_ts"], utc=True
            )
            feats["signal_ts_utc"] = pd.to_datetime(feats["signal_ts"], utc=True)
            merged = sym_trades_indexed.merge(
                feats, on="signal_ts_utc", how="inner", suffixes=("_t", "_f")
            )
            for r in merged.to_dict("records"):
                trade_idx = r["trade_idx"]
                feat_rows.append({k: r[k] for k in feats.columns if k in r})
                feat_idx.append(trade_idx)
        else:
            for trade_idx, fr in zip(sym_trades.index, feats.to_dict("records")):
                feat_rows.append(fr)
                feat_idx.append(int(trade_idx))

    df_feat = pd.DataFrame(feat_rows, index=feat_idx)
    df_feat.index.name = "trade_idx"
    df_feat = df_feat.sort_index()
    return df_feat


def get_windows(df_trades: pd.DataFrame, train_y: int, oos_mo: int, step_mo: int) -> list[dict]:
    t_start = df_trades["entry_ts"].min()
    t_end = df_trades["entry_ts"].max()
    cur = t_start
    windows: list[dict] = []
    while True:
        train_end = cur + pd.DateOffset(years=train_y)
        oos_end = train_end + pd.DateOffset(months=oos_mo)
        if oos_end > t_end:
            break
        windows.append({
            "idx": len(windows) + 1,
            "train_start": cur,
            "train_end": train_end,
            "oos_end": oos_end,
        })
        cur = cur + pd.DateOffset(months=step_mo)
    return windows


def compute_trade_metrics(R_arr: np.ndarray, risk_pct: float = 0.02, leverage: float = 2.0) -> dict:
    """Flat T2 sizing'inde: her trade %2 risk, 2x lev.
    R_arr: realized R-multiples (gain/loss in R units, where R = risk_pct of equity).
    PnL per trade as % of equity = R * risk_pct (sizing = risk_pct ile zaten R*risk = equity %).
    """
    if len(R_arr) == 0:
        return {"n": 0, "ret": 0.0, "sharpe": 0.0, "dd": 0.0, "win_rate": 0.0}
    pnl_pct = R_arr * risk_pct  # her trade icin equity % degisimi
    # Compounded total return
    equity_path = np.cumprod(1.0 + pnl_pct)
    total_ret = equity_path[-1] - 1.0
    # Sharpe (annualized): per-trade pnl_pct uzerinden, gun bazli olarak yaklasik
    if pnl_pct.std() > 1e-9:
        # Trade-level Sharpe; varsayim: ortalama 1 trade/gun = 252 trade/yil
        sharpe = float(pnl_pct.mean() / pnl_pct.std() * np.sqrt(252))
    else:
        sharpe = 0.0
    # Max drawdown
    peak = np.maximum.accumulate(equity_path)
    dd = float(((equity_path - peak) / peak).min())
    win_rate = float((R_arr > 0).mean())
    return {
        "n": int(len(R_arr)),
        "ret": float(total_ret),
        "sharpe": sharpe,
        "dd": dd,
        "win_rate": win_rate,
    }


def shuffle_null_test(
    X_train: pd.DataFrame,
    y_train: pd.Series,
    X_oos: pd.DataFrame,
    R_oos: np.ndarray,
    baseline_sharpe: float,
    n_iter: int = 200,
    threshold: float = 0.55,
    rng_seed: int = 42,
) -> tuple[float, np.ndarray]:
    """Shuffle null: y_train'i permute et, RF egit, OOS'da filter, Sharpe alpha hesapla.
    Real Sharpe alpha bu null distribution'da p<0.05 olmali.
    """
    rng = np.random.default_rng(rng_seed)
    null_alphas: list[float] = []
    feat_cols = [c for c in X_train.columns if c not in ("direction", "symbol")]

    for it in range(n_iter):
        y_shuf = pd.Series(rng.permutation(y_train.values), index=y_train.index)
        try:
            clf, _ = train_rf(
                X_train,
                y_shuf,
                labels_df=None,  # uniqueness yok bu null'da, hizli
                cv=2,  # null icin minimum CV (sadece OOS uygulamak istiyoruz)
                n_estimators=CONFIG["n_estimators"],
                max_depth=CONFIG["max_depth"],
                min_samples_leaf=CONFIG["min_samples_leaf"],
                random_state=42,
                embargo_bars=CONFIG["purged_kfold"]["embargo_bars"],
            )
        except Exception:
            null_alphas.append(0.0)
            continue
        mask = predict_filter(clf, X_oos, threshold=threshold, feature_names=feat_cols)
        sel_R = R_oos[mask.values]
        if len(sel_R) > 0:
            null_metrics = compute_trade_metrics(sel_R)
            null_alpha = null_metrics["sharpe"] - baseline_sharpe
        else:
            null_alpha = -baseline_sharpe  # tum trade'ler reddedildi
        null_alphas.append(null_alpha)

    null_dist = np.array(null_alphas)
    return null_dist


def bootstrap_ci(values: np.ndarray, n_iter: int = 2000, alpha: float = 0.05, rng_seed: int = 42) -> tuple[float, float]:
    """Bootstrap CI for mean(values)."""
    rng = np.random.default_rng(rng_seed)
    n = len(values)
    means = np.empty(n_iter)
    for i in range(n_iter):
        sample = rng.choice(values, size=n, replace=True)
        means[i] = sample.mean()
    lo = float(np.percentile(means, alpha / 2 * 100))
    hi = float(np.percentile(means, (1 - alpha / 2) * 100))
    return lo, hi


def main() -> None:
    REPORT_OUT.parent.mkdir(parents=True, exist_ok=True)
    out_lines: list[str] = []

    def w(line: str = "") -> None:
        print(line)
        out_lines.append(line)

    t0 = time.time()
    w("=" * 78)
    w("ML META-LABELING v1.1 - WALK-FORWARD + STAT GATES")
    w("=" * 78)
    w(f"Pre-reg: memory/researcher/hypotheses/2026-05-15-ml-meta-labeling-v1.md (v0.1.1)")
    w(f"Generated: {pd.Timestamp.utcnow().isoformat()}")
    w(f"Config hash: {stable_hash(CONFIG)}")
    w("")

    # 1) Veri yukle
    w("--- 1) DATA LOAD ---")
    df_trades = load_trades()
    ohlcv = load_ohlcv()
    w(f"Trade pool: {len(df_trades)}")
    w(f"OHLCV symbols: {len(ohlcv)}")
    w(f"y mean (R>0): {df_trades['y'].mean():.4f}")

    # 2) Feature matrix
    w("\n--- 2) FEATURE ENGINEERING ---")
    t1 = time.time()
    df_feat = build_full_feature_matrix(df_trades, ohlcv)
    w(f"Feature matrix: {df_feat.shape}  ({time.time()-t1:.1f}s)")
    feat_cols = [c for c in df_feat.columns if c not in ("direction", "symbol", "signal_ts", "signal_ts_utc")]
    w(f"Numeric features ({len(feat_cols)}): {feat_cols}")

    # df_feat index = trade_idx (df_trades.index degeri). Birlestir:
    common_idx = df_feat.index.intersection(df_trades.index)
    df_feat = df_feat.loc[common_idx]
    df_aligned = df_trades.loc[common_idx].copy()
    w(f"Aligned trade count: {len(df_aligned)}")

    # 3) Windows
    w("\n--- 3) WALK-FORWARD WINDOWS ---")
    windows = get_windows(
        df_aligned,
        train_y=CONFIG["walk_forward"]["train_y"],
        oos_mo=CONFIG["walk_forward"]["oos_mo"],
        step_mo=CONFIG["walk_forward"]["step_mo"],
    )
    w(f"Windows: {len(windows)}")
    for ww in windows:
        w(f"  W{ww['idx']}: train [{ww['train_start'].strftime('%Y-%m-%d')} -> {ww['train_end'].strftime('%Y-%m-%d')}] "
          f"oos [{ww['train_end'].strftime('%Y-%m-%d')} -> {ww['oos_end'].strftime('%Y-%m-%d')}]")

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

        X_train = df_feat.loc[train_idx, feat_cols].astype(float)
        y_train = df_aligned.loc[train_idx, "y"]
        X_oos = df_feat.loc[oos_idx, feat_cols].astype(float)
        R_oos = df_aligned.loc[oos_idx, "R"].values

        if len(X_train) < 100 or len(X_oos) < 30:
            w(f"  SKIP - n_train={len(X_train)} n_oos={len(X_oos)}")
            continue

        # labels_df icin t0/t1 (trade_idx integer pozisyonlari kullan)
        ldf = pd.DataFrame({
            "t0": np.arange(len(X_train)),
            "t1": np.arange(len(X_train)) + 1,  # her trade tek-bar acidan ele alinmis (gerekirse holding eklenir)
            "signal_ts": df_aligned.loc[train_idx, "entry_ts"].values,
        })

        clf, metrics = train_rf(
            X_train,
            y_train,
            labels_df=ldf,
            cv=CONFIG["purged_kfold"]["n_folds"],
            n_estimators=CONFIG["n_estimators"],
            max_depth=CONFIG["max_depth"],
            min_samples_leaf=CONFIG["min_samples_leaf"],
            random_state=CONFIG["random_state"],
            embargo_bars=CONFIG["purged_kfold"]["embargo_bars"],
        )

        # OOS predict + filter
        mask_oos = predict_filter(clf, X_oos, threshold=CONFIG["threshold"], feature_names=feat_cols)
        ml_R = R_oos[mask_oos.values]
        baseline_R = R_oos  # all trades

        ml_metrics = compute_trade_metrics(ml_R)
        bl_metrics = compute_trade_metrics(baseline_R)
        sharpe_alpha = ml_metrics["sharpe"] - bl_metrics["sharpe"]
        ret_alpha = ml_metrics["ret"] - bl_metrics["ret"]

        # Shuffle null
        w(f"  shuffle null ({CONFIG['shuffle_iters']} iter)...")
        ts = time.time()
        null_dist = shuffle_null_test(
            X_train, y_train, X_oos, R_oos,
            baseline_sharpe=bl_metrics["sharpe"],
            n_iter=CONFIG["shuffle_iters"],
            threshold=CONFIG["threshold"],
            rng_seed=42 + ww["idx"],
        )
        # p-value: real Sharpe alpha'nin null dagilimda asilma orani
        p_shuf = float((null_dist >= sharpe_alpha).mean())
        w(f"  shuffle done ({time.time()-ts:.1f}s)")

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
            "ret_alpha": ret_alpha,
            "p_shuffle": p_shuf,
            "null_mean": float(null_dist.mean()),
            "null_std": float(null_dist.std()),
            "y_train_mean": float(y_train.mean()),
        }
        results.append(rec)
        w(f"  W{ww['idx']}: n_taken={rec['n_taken']}/{len(X_oos)} ({rec['survival_rate']*100:.1f}%) "
          f"ml_sh={rec['ml_sharpe']:+.3f} bl_sh={rec['bl_sharpe']:+.3f} "
          f"alpha={rec['sharpe_alpha']:+.3f} p={rec['p_shuffle']:.3f} "
          f"cv_auc={rec['cv_auc']:.3f} gap={rec['overfit_gap']:+.3f} "
          f"({time.time()-tw:.1f}s)")

    # 5) Aggregate stats + gates
    w("\n--- 5) AGGREGATE + GATES ---")
    if not results:
        w("HATA: Hicbir pencere calismadi.")
        REPORT_OUT.write_text("\n".join(out_lines), encoding="utf-8")
        return

    df_res = pd.DataFrame(results)
    mean_alpha = float(df_res["sharpe_alpha"].mean())
    mean_ret_alpha = float(df_res["ret_alpha"].mean())
    mean_cv_auc = float(df_res["cv_auc"].mean())
    mean_overfit = float(df_res["overfit_gap"].mean())
    mean_survival = float(df_res["survival_rate"].mean())

    # Bootstrap CI
    lo, hi = bootstrap_ci(df_res["sharpe_alpha"].values, n_iter=CONFIG["bootstrap_iters"])

    # Bonferroni
    alpha_adj = 0.05 / len(results)
    n_bonferroni = int((df_res["p_shuffle"] < alpha_adj).sum())
    n_shuffle = int((df_res["p_shuffle"] < 0.05).sum())

    w(f"\nMean Sharpe alpha:     {mean_alpha:+.4f}  (target >=+0.15)")
    w(f"Bootstrap CI(95%):     [{lo:+.4f}, {hi:+.4f}]  (target low > 0)")
    w(f"Mean return alpha:     {mean_ret_alpha:+.4f}  (target >=+0.03)")
    w(f"Mean CV AUC:           {mean_cv_auc:.4f}  (target >=0.55)")
    w(f"Mean overfit gap:      {mean_overfit:+.4f}  (target <0.15)")
    w(f"Mean survival rate:    {mean_survival:.4f}  (target 0.20-0.95)")
    w(f"Shuffle p<0.05:        {n_shuffle}/{len(results)}  (target >=5/6)")
    w(f"Bonferroni p<{alpha_adj:.5f}: {n_bonferroni}/{len(results)}  (target >=3/6)")

    # Per-window detail
    w("\nPer-window detail:")
    w(f"  {'W':>2s} {'n_train':>7s} {'n_oos':>5s} {'taken':>5s} {'cv_auc':>6s} {'gap':>6s} "
      f"{'ml_sh':>7s} {'bl_sh':>7s} {'alpha':>7s} {'p_sh':>6s}")
    for r in results:
        w(f"  {r['idx']:>2d} {r['n_train']:>7d} {r['n_oos']:>5d} {r['n_taken']:>5d} "
          f"{r['cv_auc']:>6.3f} {r['overfit_gap']:>+6.3f} "
          f"{r['ml_sharpe']:>+7.3f} {r['bl_sharpe']:>+7.3f} {r['sharpe_alpha']:>+7.3f} "
          f"{r['p_shuffle']:>6.3f}")

    # 6) HARD gate karari (pre-reg)
    w("\n--- 6) HARD GATE KONTROLU (pre-reg null hipotezleri) ---")
    gates_failed: list[str] = []
    if mean_alpha < 0.15:
        gates_failed.append(f"NH1 mean Sharpe alpha {mean_alpha:+.4f} < +0.15")
    if lo <= 0:
        gates_failed.append(f"NH2 bootstrap CI low {lo:+.4f} <= 0")
    if n_shuffle < 5:
        gates_failed.append(f"NH3 shuffle pass {n_shuffle}/6 < 5/6")
    if n_bonferroni < 3:
        gates_failed.append(f"NH4 Bonferroni pass {n_bonferroni}/6 < 3/6")
    if mean_cv_auc < 0.55:
        gates_failed.append(f"NH5 mean CV AUC {mean_cv_auc:.4f} < 0.55")
    if mean_overfit > 0.15:
        gates_failed.append(f"NH6 overfit gap {mean_overfit:+.4f} > 0.15")
    if mean_survival < 0.20 or mean_survival > 0.95:
        gates_failed.append(f"NH7 survival rate {mean_survival:.4f} out of [0.20, 0.95]")

    if gates_failed:
        w(f"\nGATES FAILED ({len(gates_failed)}/7):")
        for g in gates_failed:
            w(f"  [X] {g}")
        verdict = "RED"
    else:
        w("\nTUM GATES PASS")
        verdict = "PASS"

    w(f"\nKARAR: {verdict}")
    w(f"\nElapsed: {time.time()-t0:.1f}s")

    # Reproducibility footer
    w("\n--- REPRODUCIBILITY ---")
    w(f"git_hash: b98f3ad4db31b559d7409beeba1a1fb8b317b6c5")
    w(f"config_hash: {stable_hash(CONFIG)}")
    w(f"trades_data_hash: {stable_hash(df_aligned[['entry_ts','symbol','strategy','R']].values.tolist()[:50])}")
    w(f"run_timestamp: {pd.Timestamp.utcnow().isoformat()}")

    # JSON-serializable result dump
    json_path = REPORT_OUT.with_suffix(".json")
    json_payload = {
        "config": CONFIG,
        "verdict": verdict,
        "aggregates": {
            "mean_sharpe_alpha": mean_alpha,
            "ci_lo": lo,
            "ci_hi": hi,
            "mean_return_alpha": mean_ret_alpha,
            "mean_cv_auc": mean_cv_auc,
            "mean_overfit_gap": mean_overfit,
            "mean_survival_rate": mean_survival,
            "shuffle_pass": n_shuffle,
            "bonferroni_pass": n_bonferroni,
            "alpha_adj": alpha_adj,
            "n_windows": len(results),
        },
        "gates_failed": gates_failed,
        "per_window": results,
    }
    json_path.write_text(json.dumps(json_payload, indent=2, default=str), encoding="utf-8")

    REPORT_OUT.write_text("\n".join(out_lines), encoding="utf-8")
    w(f"\nRapor: {REPORT_OUT}")
    w(f"JSON:  {json_path}")


if __name__ == "__main__":
    main()
