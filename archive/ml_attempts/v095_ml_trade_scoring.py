"""v0.9.5 — ML Trade Scoring Filter.

Pipeline:
  1) 4787 trade'i topla (cache'le).
  2) Feature engineering: BTC + sembol bazli OHLCV ozellikleri, zaman, konsantrasyon.
  3) Walk-forward CV (3y train -> 1y test, 6mo slide) ile GradientBoostingClassifier.
  4) Threshold sweep (0.50..0.70): kac trade kalir, ROI/DD nasil etkilenir.
  5) Score dict'i `production_replay`'e ver, 3y rolling 13 pencere stress.
  6) Permutation importance + sanity checks (overfit gap, shuffle null, ablation).

Output: reports/v095_ml_results.txt
"""
from __future__ import annotations

import json
import os
import pickle
import sys
import warnings
from datetime import timedelta
from pathlib import Path
from statistics import mean, median

os.environ["PA_LOG_QUIET"] = "1"
warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from price_action.backtest.lab import ProductionConfig, production_replay
from scripts.v09_optimize_top10 import TOP_10, SYMBOLS_11, _gather  # noqa: E402

TRADES_CACHE = ROOT / "data" / "v095_trades_cache.pkl"
OHLCV_CACHE = ROOT / "data" / "v095_ohlcv_cache.pkl"
REPORT_OUT = ROOT / "reports" / "v095_ml_results.txt"


# =============================================================
# 1) Trade gathering (cache)
# =============================================================
def load_trades() -> list[dict]:
    if TRADES_CACHE.exists():
        with TRADES_CACHE.open("rb") as f:
            return pickle.load(f)
    print("Trade'leri topluyor (TOP_10 x 11 sembol)...")
    out: list[dict] = []
    for m, c in TOP_10:
        trs = _gather(m, c)
        out.extend(trs)
        print(f"  {m}: {len(trs)}")
    out.sort(key=lambda x: x["entry_ts"])
    with TRADES_CACHE.open("wb") as f:
        pickle.dump(out, f)
    print(f"Toplam: {len(out)}")
    return out


# =============================================================
# 2) OHLCV cache (sembol bazli)
# =============================================================
def load_ohlcv_all() -> dict[str, pd.DataFrame]:
    if OHLCV_CACHE.exists():
        with OHLCV_CACHE.open("rb") as f:
            return pickle.load(f)
    from scripts.run_real_backtest import _load_symbol_ohlcv
    d: dict[str, pd.DataFrame] = {}
    for sym in SYMBOLS_11:
        df = _load_symbol_ohlcv(sym, tf="1d")
        if df is None or df.empty:
            continue
        df = df.sort_values("ts").reset_index(drop=True)
        # ATR%
        high = df["high"]; low = df["low"]; close = df["close"]
        tr1 = (high - low).abs()
        tr2 = (high - close.shift(1)).abs()
        tr3 = (low - close.shift(1)).abs()
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        atr14 = tr.rolling(14).mean()
        df["atr_pct"] = (atr14 / close) * 100.0
        df["ret_7"] = close.pct_change(7) * 100.0
        df["ret_20"] = close.pct_change(20) * 100.0
        df["ret_30"] = close.pct_change(30) * 100.0
        df["ema200"] = close.ewm(span=200, adjust=False).mean()
        df["above_ema200"] = (close > df["ema200"]).astype(int)
        # streak: above_ema200 ardisik gun
        streak = []
        cur = 0
        prev = None
        for v in df["above_ema200"].tolist():
            if prev is None or v != prev:
                cur = 1 if v == 1 else -1
            else:
                if v == 1:
                    cur += 1
                else:
                    cur -= 1
            streak.append(cur)
            prev = v
        df["ema200_streak"] = streak
        # 90d drawdown — close'tan 90gun tepe
        roll_max = close.rolling(90, min_periods=10).max()
        df["dd_90d"] = (close / roll_max - 1.0) * 100.0
        # volume z (20d)
        vol = df["volume"]
        df["vol_z_20"] = (vol - vol.rolling(20).mean()) / (vol.rolling(20).std() + 1e-9)
        df["ts_date"] = df["ts"].dt.date
        df = df.set_index("ts_date")
        d[sym] = df
    with OHLCV_CACHE.open("wb") as f:
        pickle.dump(d, f)
    return d


# =============================================================
# 3) Feature engineering
# =============================================================
def build_features(trades: list[dict], ohlcv: dict[str, pd.DataFrame]) -> pd.DataFrame:
    btc = ohlcv.get("BTC/USDT")
    rows = []
    # Konsantrasyon (concurrent open) icin trade'leri sirala
    # Onceki trade'ler: entry_ts < current, exit_ts > current
    sorted_trs = sorted(trades, key=lambda t: t["entry_ts"])
    # Index'li liste
    entries = [(t["entry_ts"], t["exit_ts"], t["side"], t["symbol"]) for t in sorted_trs]
    for t in sorted_trs:
        d_key = t["entry_ts"].date()
        # BTC features
        btc_atr = btc_streak = btc_dd90 = btc_ret7 = btc_ret30 = np.nan
        if btc is not None and d_key in btc.index:
            row = btc.loc[d_key]
            btc_atr = float(row["atr_pct"]) if pd.notna(row["atr_pct"]) else np.nan
            btc_streak = float(row["ema200_streak"]) if pd.notna(row["ema200_streak"]) else np.nan
            btc_dd90 = float(row["dd_90d"]) if pd.notna(row["dd_90d"]) else np.nan
            btc_ret7 = float(row["ret_7"]) if pd.notna(row["ret_7"]) else np.nan
            btc_ret30 = float(row["ret_30"]) if pd.notna(row["ret_30"]) else np.nan
        # Sembol features
        sdf = ohlcv.get(t["symbol"])
        sym_atr = sym_volz = sym_ret20 = sym_streak = np.nan
        if sdf is not None and d_key in sdf.index:
            row = sdf.loc[d_key]
            sym_atr = float(row["atr_pct"]) if pd.notna(row["atr_pct"]) else np.nan
            sym_volz = float(row["vol_z_20"]) if pd.notna(row["vol_z_20"]) else np.nan
            sym_ret20 = float(row["ret_20"]) if pd.notna(row["ret_20"]) else np.nan
            sym_streak = float(row["ema200_streak"]) if pd.notna(row["ema200_streak"]) else np.nan
        # SL pct
        sl_pct = abs(t["entry_price"] - t["initial_sl"]) / t["entry_price"]
        # Concurrent open positions (ayni side)
        side = t["side"]
        ets = t["entry_ts"]
        conc_same_side = sum(
            1 for (e, x, s, sym) in entries
            if e < ets and x > ets and s == side
        )
        conc_total = sum(
            1 for (e, x, s, sym) in entries
            if e < ets and x > ets
        )
        rows.append({
            "entry_ts": t["entry_ts"],
            "exit_ts": t["exit_ts"],
            "symbol": t["symbol"],
            "side": t["side"],
            "strategy": t["strategy"],
            "R": t["R"],
            "win": int(t["R"] > 0),
            "conf": t["conf"],
            "vol_z": t["vol_z"],
            "sl_pct": sl_pct * 100.0,
            "btc_atr_pct": btc_atr,
            "btc_ema200_streak": btc_streak,
            "btc_dd_90d": btc_dd90,
            "btc_ret_7": btc_ret7,
            "btc_ret_30": btc_ret30,
            "sym_atr_pct": sym_atr,
            "sym_vol_z_20": sym_volz,
            "sym_ret_20": sym_ret20,
            "sym_ema200_streak": sym_streak,
            "month": t["entry_ts"].month,
            "weekday": t["entry_ts"].weekday(),
            "conc_same_side": conc_same_side,
            "conc_total": conc_total,
            "is_long": 1 if str(t["side"]).lower() == "long" else 0,
        })
    df = pd.DataFrame(rows)
    # Strategy one-hot (sayisal feature olarak)
    strat_dummies = pd.get_dummies(df["strategy"], prefix="strat")
    df = pd.concat([df, strat_dummies], axis=1)
    # Symbol one-hot
    sym_dummies = pd.get_dummies(df["symbol"], prefix="sym")
    df = pd.concat([df, sym_dummies], axis=1)
    return df


# =============================================================
# 4) Feature/target cols
# =============================================================
BASE_FEATURES = [
    "conf", "vol_z", "sl_pct",
    "btc_atr_pct", "btc_ema200_streak", "btc_dd_90d", "btc_ret_7", "btc_ret_30",
    "sym_atr_pct", "sym_vol_z_20", "sym_ret_20", "sym_ema200_streak",
    "month", "weekday", "conc_same_side", "conc_total", "is_long",
]


def feature_cols(df: pd.DataFrame) -> list[str]:
    cols = list(BASE_FEATURES)
    cols += [c for c in df.columns if c.startswith("strat_") or c.startswith("sym_") and c != "sym_atr_pct" and c != "sym_vol_z_20" and c != "sym_ret_20" and c != "sym_ema200_streak"]
    # Sym one-hot ile sym_atr_pct gibi feature'lari karistirma — explicit sec
    cols = list(dict.fromkeys(cols))  # uniq
    return [c for c in cols if c in df.columns]


# =============================================================
# 5) Walk-forward CV — score her trade icin OOF
# =============================================================
def walk_forward_score(df: pd.DataFrame, feat_cols: list[str],
                       train_years: float = 3.0, test_years: float = 0.5,
                       slide_months: int = 3, verbose: bool = True) -> tuple[pd.Series, list[dict]]:
    """OOF proba dondur. Ayrica fold-by-fold metrik listesi.

    REGULARIZED: 3y train, 6mo test, 3mo slide -> daha siki OOF coverage.
    max_depth=3 + n_estimators=80 -> overfit'i azalt (orig 4/150 cok overfit etti).
    """
    from sklearn.ensemble import GradientBoostingClassifier
    df = df.sort_values("entry_ts").reset_index(drop=True)
    df["oof_proba"] = np.nan
    df["fold"] = -1
    folds = []
    start = df["entry_ts"].min()
    end = df["entry_ts"].max()
    train_td = pd.Timedelta(days=int(train_years * 365))
    test_td = pd.Timedelta(days=int(test_years * 365))
    slide_td = pd.Timedelta(days=int(slide_months * 30))
    cur = start
    fold_idx = 0
    while cur + train_td + test_td <= end + slide_td:
        tr_start = cur
        tr_end = cur + train_td
        te_end = tr_end + test_td
        tr_mask = (df["entry_ts"] >= tr_start) & (df["entry_ts"] < tr_end)
        te_mask = (df["entry_ts"] >= tr_end) & (df["entry_ts"] < te_end)
        n_tr = tr_mask.sum()
        n_te = te_mask.sum()
        if n_tr < 100 or n_te < 20:
            cur += slide_td
            continue
        X_tr = df.loc[tr_mask, feat_cols].fillna(0.0).astype(float).values
        y_tr = df.loc[tr_mask, "win"].astype(int).values
        X_te = df.loc[te_mask, feat_cols].fillna(0.0).astype(float).values
        y_te = df.loc[te_mask, "win"].astype(int).values
        # class imbalance: sample_weight
        pos = (y_tr == 1).sum(); neg = (y_tr == 0).sum()
        sw = np.where(y_tr == 1, neg/max(pos, 1), 1.0).astype(float)
        # Regularized: depth=3, n_est=80, min_samples_leaf=30, max_features='sqrt'
        clf = GradientBoostingClassifier(
            n_estimators=80, max_depth=3, learning_rate=0.05,
            subsample=0.7, max_features="sqrt",
            min_samples_leaf=30, random_state=42,
        )
        clf.fit(X_tr, y_tr, sample_weight=sw)
        # Train WR vs test WR (overfit gap)
        tr_pred = (clf.predict_proba(X_tr)[:, 1] >= 0.5).astype(int)
        tr_wr = (tr_pred & y_tr).sum() / max(tr_pred.sum(), 1)
        te_proba = clf.predict_proba(X_te)[:, 1]
        te_pred = (te_proba >= 0.5).astype(int)
        te_wr = (te_pred & y_te).sum() / max(te_pred.sum(), 1)
        df.loc[te_mask, "oof_proba"] = te_proba
        df.loc[te_mask, "fold"] = fold_idx
        folds.append({
            "fold": fold_idx, "tr_start": tr_start, "tr_end": tr_end, "te_end": te_end,
            "n_tr": int(n_tr), "n_te": int(n_te),
            "train_pred_wr": float(tr_wr), "test_pred_wr": float(te_wr),
            "train_base_wr": float(y_tr.mean()), "test_base_wr": float(y_te.mean()),
        })
        if verbose:
            print(f"  fold {fold_idx}: train {tr_start.date()}-{tr_end.date()} (n={n_tr}) "
                  f"test (n={n_te}) train-pred-WR={tr_wr:.2%} test-pred-WR={te_wr:.2%}")
        cur += slide_td
        fold_idx += 1
    return df["oof_proba"], folds


# =============================================================
# 6) Score dict olustur (sym, entry_ts) -> proba
# =============================================================
def make_score_filter(df: pd.DataFrame, proba_col: str = "oof_proba") -> dict:
    out = {}
    for _, row in df.iterrows():
        if pd.notna(row[proba_col]):
            out[(row["symbol"], row["entry_ts"])] = float(row[proba_col])
    return out


# =============================================================
# 7) Backtest helpers
# =============================================================
def trades_to_dicts(df: pd.DataFrame, trades_raw: list[dict]) -> list[dict]:
    """Filter trades_raw to those that have OOF proba (i.e. in test window)."""
    keys = set()
    for _, row in df.iterrows():
        if pd.notna(row["oof_proba"]):
            keys.add((row["symbol"], row["entry_ts"]))
    return [t for t in trades_raw if (t["symbol"], t["entry_ts"]) in keys]


def threshold_sweep(trades_raw: list[dict], df: pd.DataFrame, thresholds: list[float],
                    base_cfg: ProductionConfig) -> list[dict]:
    """Tek pencere (tum OOF range) threshold sweep."""
    # OOF olan trade'leri kullan
    keys_with_proba = {(r["symbol"], r["entry_ts"]): r["oof_proba"]
                       for _, r in df.iterrows() if pd.notna(r["oof_proba"])}
    trades_oof = [t for t in trades_raw if (t["symbol"], t["entry_ts"]) in keys_with_proba]
    if not trades_oof:
        return []
    years = (trades_oof[-1]["entry_ts"] - trades_oof[0]["entry_ts"]).days / 365.25
    out = []
    # Baseline (no filter)
    r = production_replay(trades_oof, base_cfg)
    if r:
        out.append({"thr": None, "n": r.trades, "final": r.final_equity, "ann": r.annualized(years),
                    "dd": r.max_drawdown, "wr": r.win_rate})
    for thr in thresholds:
        cfg = base_cfg.with_overrides(score_filter=keys_with_proba, score_threshold=thr)
        r = production_replay(trades_oof, cfg)
        if r is None:
            out.append({"thr": thr, "n": 0, "final": 0, "ann": 0, "dd": 0, "wr": 0})
            continue
        out.append({"thr": thr, "n": r.trades, "final": r.final_equity, "ann": r.annualized(years),
                    "dd": r.max_drawdown, "wr": r.win_rate})
    return out


def rolling_3y_stress(trades_raw: list[dict], df: pd.DataFrame, cfg: ProductionConfig,
                      use_filter: bool, threshold: float = 0.0,
                      pass_through_no_score: bool = True) -> dict:
    """3y rolling 13 pencere ortalama.

    pass_through_no_score=True: OOF score yoksa trade'i KABUL et (filter pass-through).
      Bu walk-forward CV'nin ilk train window'unda OOF olmayan eski trade'leri korur.
    pass_through_no_score=False: score yok = skip (default lab davranisi).
    """
    score_dict = None
    if use_filter:
        score_dict = {(r["symbol"], r["entry_ts"]): r["oof_proba"]
                      for _, r in df.iterrows() if pd.notna(r["oof_proba"])}
        if pass_through_no_score:
            # Score'u olmayan tum trade'leri 1.0 (her zaman pass) ile doldur
            all_keys = {(t["symbol"], t["entry_ts"]) for t in trades_raw}
            for k in all_keys:
                if k not in score_dict:
                    score_dict[k] = 1.0
        cfg = cfg.with_overrides(score_filter=score_dict, score_threshold=threshold)
    if not trades_raw:
        return {}
    start = trades_raw[0]["entry_ts"]
    end = trades_raw[-1]["exit_ts"]
    windows = []
    cur = start
    while cur + pd.Timedelta(days=3*365) <= end:
        windows.append((cur, cur + pd.Timedelta(days=3*365)))
        cur += pd.Timedelta(days=60)
    anns, dds = [], []
    n_per = []
    for ws, we in windows:
        w = [t for t in trades_raw if ws <= t["entry_ts"] < we]
        r = production_replay(w, cfg)
        if r is None:
            continue
        anns.append(r.annualized(3.0)*100)
        dds.append(r.max_drawdown*100)
        n_per.append(r.trades)
    if not anns:
        return {}
    return {
        "n_windows": len(anns),
        "ann_mean": mean(anns), "ann_med": median(anns),
        "ann_min": min(anns), "ann_max": max(anns),
        "dd_mean": mean(dds), "dd_min": min(dds),
        "risk_adj": mean(anns) / abs(mean(dds)) if mean(dds) != 0 else 0,
        "n_mean": mean(n_per) if n_per else 0,
    }


# =============================================================
# 8) Sanity checks
# =============================================================
def overfitting_gap(folds: list[dict]) -> dict:
    train_wrs = [f["train_pred_wr"] for f in folds]
    test_wrs = [f["test_pred_wr"] for f in folds]
    return {
        "train_mean": mean(train_wrs) if train_wrs else 0,
        "test_mean": mean(test_wrs) if test_wrs else 0,
        "gap": (mean(train_wrs) - mean(test_wrs)) if train_wrs else 0,
    }


def shuffle_null(df: pd.DataFrame, feat_cols: list[str], n_iter: int = 5) -> dict:
    """Target'i shuffle et, OOF mean WR baseline'a yakin mi kontrol."""
    from sklearn.ensemble import GradientBoostingClassifier
    df_s = df.copy()
    test_wrs = []
    rng = np.random.default_rng(123)
    for _ in range(n_iter):
        y_shuf = rng.permutation(df_s["win"].values)
        df_s["win"] = y_shuf
        # Tek fold (basitlik): ilk %70 train, son %30 test
        n = len(df_s)
        tr_end = int(n * 0.7)
        X_tr = df_s.iloc[:tr_end][feat_cols].fillna(0.0).astype(float).values
        y_tr = df_s.iloc[:tr_end]["win"].astype(int).values
        X_te = df_s.iloc[tr_end:][feat_cols].fillna(0.0).astype(float).values
        y_te = df_s.iloc[tr_end:]["win"].astype(int).values
        clf = GradientBoostingClassifier(n_estimators=100, max_depth=4, learning_rate=0.05,
                                          subsample=0.8, random_state=0)
        clf.fit(X_tr, y_tr)
        proba = clf.predict_proba(X_te)[:, 1]
        # top 50% prediction
        pred = (proba >= 0.5).astype(int)
        wr = (pred & y_te).sum() / max(pred.sum(), 1)
        test_wrs.append(wr)
    return {"mean": mean(test_wrs), "n": n_iter}


def feature_ablation(df: pd.DataFrame, trades_raw: list[dict], base_cfg: ProductionConfig,
                      ablation_sets: dict[str, list[str]], threshold: float = 0.55) -> dict:
    """Her feature alt-seti icin 3y rolling stress dondur."""
    out = {}
    for name, cols in ablation_sets.items():
        # Sadece cols ile train
        df_local = df.copy()
        proba, _ = walk_forward_score(df_local, cols, verbose=False)
        df_local["oof_proba"] = proba
        stats = rolling_3y_stress(trades_raw, df_local, base_cfg, use_filter=True, threshold=threshold)
        out[name] = stats
    return out


# =============================================================
# 9) Permutation importance (lightweight)
# =============================================================
def permutation_importance(df: pd.DataFrame, feat_cols: list[str], top_k: int = 10) -> list[tuple]:
    """Tum data train, hold-out son %30 test, her feature permute -> WR delta."""
    from sklearn.ensemble import GradientBoostingClassifier
    df_s = df.sort_values("entry_ts").reset_index(drop=True)
    n = len(df_s)
    tr_end = int(n * 0.7)
    X_tr = df_s.iloc[:tr_end][feat_cols].fillna(0.0).astype(float).values
    y_tr = df_s.iloc[:tr_end]["win"].astype(int).values
    X_te = df_s.iloc[tr_end:][feat_cols].fillna(0.0).astype(float).copy().values
    y_te = df_s.iloc[tr_end:]["win"].astype(int).values
    clf = GradientBoostingClassifier(n_estimators=150, max_depth=4, learning_rate=0.05,
                                      subsample=0.8, random_state=42)
    clf.fit(X_tr, y_tr)
    base_proba = clf.predict_proba(X_te)[:, 1]
    base_pred = (base_proba >= 0.5).astype(int)
    base_wr = (base_pred & y_te).sum() / max(base_pred.sum(), 1)
    rng = np.random.default_rng(7)
    imps = []
    for i, c in enumerate(feat_cols):
        X_pert = X_te.copy()
        rng.shuffle(X_pert[:, i])
        proba = clf.predict_proba(X_pert)[:, 1]
        pred = (proba >= 0.5).astype(int)
        wr = (pred & y_te).sum() / max(pred.sum(), 1)
        imps.append((c, base_wr - wr))
    imps.sort(key=lambda x: -x[1])
    return imps[:top_k]


# =============================================================
# Main
# =============================================================
def main():
    lines = []

    def log(s=""):
        print(s)
        lines.append(s)

    log("=" * 110)
    log("v0.9.5 ML TRADE SCORING — full pipeline")
    log("=" * 110)

    trades_raw = load_trades()
    log(f"\nTotal trades: {len(trades_raw)}")
    log(f"Trade span: {trades_raw[0]['entry_ts']} ... {trades_raw[-1]['entry_ts']}")
    log(f"Base WR: {sum(1 for t in trades_raw if t['R']>0)/len(trades_raw):.3f}")

    log("\nOHLCV cache yukle (BTC + 11 sembol)...")
    ohlcv = load_ohlcv_all()
    log(f"  yuklenen sembol: {len(ohlcv)}")

    log("\nFeature build...")
    df = build_features(trades_raw, ohlcv)
    feat_cols = feature_cols(df)
    log(f"  trade df: {df.shape}")
    log(f"  feature sayisi: {len(feat_cols)}")
    log(f"  features: {feat_cols[:20]}{'...' if len(feat_cols)>20 else ''}")

    log("\nWalk-forward CV (3y train / 1y test / 6mo slide)...")
    oof, folds = walk_forward_score(df, feat_cols, verbose=True)
    df["oof_proba"] = oof
    log(f"  folds: {len(folds)}, OOF coverage: {df['oof_proba'].notna().sum()}/{len(df)}")

    log("\nOverfitting gap kontrolu...")
    gap = overfitting_gap(folds)
    log(f"  train mean WR (pred>=0.5): {gap['train_mean']:.3%}")
    log(f"  test  mean WR (pred>=0.5): {gap['test_mean']:.3%}")
    log(f"  gap: {gap['gap']*100:+.2f}pp ({'OK <30%' if abs(gap['gap'])<0.30 else 'ALARM!'})")

    log("\nShuffle null test (target rasgele)...")
    null = shuffle_null(df, feat_cols, n_iter=5)
    real_wr = df.loc[df["oof_proba"]>=0.5, "win"].mean() if (df["oof_proba"]>=0.5).any() else 0
    log(f"  null model OOF WR (top 50%): {null['mean']:.3%}")
    log(f"  real model OOF WR (top 50%): {real_wr:.3%}")
    edge = real_wr - null["mean"]
    log(f"  edge: {edge*100:+.2f}pp ({'GERCEK EDGE' if edge>0.02 else 'EDGE YOK / ZAYIF'})")

    log("\nThreshold sweep (single-pass, OOF range)...")
    base_prod = ProductionConfig.from_yaml().with_overrides(concentration_max_per_symbol_pct=0.20)
    thresholds = [0.50, 0.55, 0.60, 0.65, 0.70]
    sweep = threshold_sweep(trades_raw, df, thresholds, base_prod)
    log(f"\n  {'thr':>5}  {'n':>5}  {'final$':>10}  {'yillik%':>8}  {'DD%':>7}  {'WR%':>5}")
    for s in sweep:
        thr_lbl = "none" if s["thr"] is None else f"{s['thr']:.2f}"
        log(f"  {thr_lbl:>5}  {s['n']:>5}  ${s['final']:>9,.0f}  {s['ann']*100:>+7.1f}%  {s['dd']*100:>+6.1f}%  {s['wr']*100:>4.0f}%")

    log("\n3y rolling stress — BASELINE (no ML filter)")
    base_stats = rolling_3y_stress(trades_raw, df, base_prod, use_filter=False)
    log(f"  windows={base_stats['n_windows']}  ann.mean={base_stats['ann_mean']:+.2f}%  "
        f"med={base_stats['ann_med']:+.2f}%  min={base_stats['ann_min']:+.1f}  max={base_stats['ann_max']:+.1f}  "
        f"DD.mean={base_stats['dd_mean']:+.1f}%  minDD={base_stats['dd_min']:+.1f}%  r-adj={base_stats['risk_adj']:.3f}")

    # ============================
    # Alternatif target: R-regressor + low-confidence cutoff
    # ============================
    log("\n--- ALT TARGET: R-regressor (E[R] proxy) ---")
    try:
        from sklearn.ensemble import GradientBoostingRegressor
        df_r = df.sort_values("entry_ts").reset_index(drop=True)
        df_r["oof_r_pred"] = np.nan
        train_td = pd.Timedelta(days=3*365)
        test_td = pd.Timedelta(days=180)
        slide_td = pd.Timedelta(days=90)
        start_r = df_r["entry_ts"].min()
        end_r = df_r["entry_ts"].max()
        cur = start_r
        while cur + train_td + test_td <= end_r + slide_td:
            tr_mask = (df_r["entry_ts"] >= cur) & (df_r["entry_ts"] < cur + train_td)
            te_mask = (df_r["entry_ts"] >= cur + train_td) & (df_r["entry_ts"] < cur + train_td + test_td)
            if tr_mask.sum() < 100 or te_mask.sum() < 20:
                cur += slide_td
                continue
            X_tr = df_r.loc[tr_mask, feat_cols].fillna(0.0).astype(float).values
            # Clip R [-2, +5] — outlier'lari kes
            y_tr = np.clip(df_r.loc[tr_mask, "R"].astype(float).values, -2.0, 5.0)
            X_te = df_r.loc[te_mask, feat_cols].fillna(0.0).astype(float).values
            reg = GradientBoostingRegressor(n_estimators=80, max_depth=3, learning_rate=0.05,
                                            subsample=0.7, min_samples_leaf=30, random_state=42)
            reg.fit(X_tr, y_tr)
            df_r.loc[te_mask, "oof_r_pred"] = reg.predict(X_te)
            cur += slide_td
        # Threshold = quantile of predicted E[R]
        valid = df_r["oof_r_pred"].notna()
        log(f"  OOF coverage: {valid.sum()}/{len(df_r)}")
        # Top 75%, 50%, 25% of predicted E[R]
        for q in [0.25, 0.50, 0.75]:
            thr_r = df_r.loc[valid, "oof_r_pred"].quantile(q)
            score_dict = {(r["symbol"], r["entry_ts"]): float(r["oof_r_pred"])
                          for _, r in df_r.iterrows() if pd.notna(r["oof_r_pred"])}
            # Pass-through
            for t in trades_raw:
                k = (t["symbol"], t["entry_ts"])
                if k not in score_dict:
                    score_dict[k] = thr_r + 1e6  # always pass
            cfg = base_prod.with_overrides(score_filter=score_dict, score_threshold=thr_r)
            # 3y rolling
            anns, dds = [], []
            start = trades_raw[0]["entry_ts"]
            end = trades_raw[-1]["exit_ts"]
            cur = start
            n_per = []
            while cur + pd.Timedelta(days=3*365) <= end:
                ws, we = cur, cur + pd.Timedelta(days=3*365)
                w = [t for t in trades_raw if ws <= t["entry_ts"] < we]
                r = production_replay(w, cfg)
                if r is not None:
                    anns.append(r.annualized(3.0)*100)
                    dds.append(r.max_drawdown*100)
                    n_per.append(r.trades)
                cur += pd.Timedelta(days=60)
            if anns:
                log(f"  R-quantile cutoff q={q:.2f} (thr_R={thr_r:+.3f}): "
                    f"n.mean={mean(n_per):.0f} ann={mean(anns):+.2f}% "
                    f"(min {min(anns):+.1f}, max {max(anns):+.1f}) "
                    f"DD={mean(dds):+.1f}% r-adj={mean(anns)/abs(mean(dds)):.3f}")
    except Exception as e:
        log(f"  R-regressor hatasi: {e}")
    # ============================

    log("\n3y rolling stress — ML filter (per-threshold)")
    ml_stats_list = []
    for thr in [0.50, 0.55, 0.60, 0.65, 0.70]:
        s = rolling_3y_stress(trades_raw, df, base_prod, use_filter=True, threshold=thr)
        if not s:
            log(f"  thr={thr}: yetersiz data")
            continue
        ml_stats_list.append((thr, s))
        log(f"  thr={thr:.2f}: windows={s['n_windows']} n.mean={s['n_mean']:.0f} "
            f"ann.mean={s['ann_mean']:+.2f}% med={s['ann_med']:+.2f}% "
            f"min={s['ann_min']:+.1f} max={s['ann_max']:+.1f}  "
            f"DD.mean={s['dd_mean']:+.1f}% minDD={s['dd_min']:+.1f}% r-adj={s['risk_adj']:.3f}")

    log("\nBALANCED preset + ML filter (kombine)")
    try:
        bal_cfg = ProductionConfig.from_yaml(str(ROOT / "configs" / "risk_balanced.yaml"))
        bal_cfg = bal_cfg.with_overrides(concentration_max_per_symbol_pct=0.20)
        for thr in [0.55, 0.60]:
            s = rolling_3y_stress(trades_raw, df, bal_cfg, use_filter=True, threshold=thr)
            if not s: continue
            log(f"  BALANCED+ML thr={thr:.2f}: ann.mean={s['ann_mean']:+.2f}% "
                f"med={s['ann_med']:+.2f}% min={s['ann_min']:+.1f} "
                f"DD.mean={s['dd_mean']:+.1f}% r-adj={s['risk_adj']:.3f}")
    except Exception as e:
        log(f"  BALANCED yukleme hatasi: {e}")

    log("\nPermutation importance (top 10)")
    imps = permutation_importance(df, feat_cols, top_k=10)
    for c, v in imps:
        log(f"  {c:<40}  delta-WR={v*100:+.2f}pp")

    log("\nFeature ablation (3y rolling, thr=0.55)")
    ablation_sets = {
        "conf_strategy_only": ["conf"] + [c for c in df.columns if c.startswith("strat_")],
        "btc_only": ["btc_atr_pct", "btc_ema200_streak", "btc_dd_90d", "btc_ret_7", "btc_ret_30"],
        "all_features": feat_cols,
    }
    try:
        abl = feature_ablation(df, trades_raw, base_prod, ablation_sets, threshold=0.55)
        for name, s in abl.items():
            if not s:
                log(f"  {name}: yetersiz")
                continue
            log(f"  {name:<22}: ann={s['ann_mean']:+.2f}% DD={s['dd_mean']:+.1f}% "
                f"n.mean={s['n_mean']:.0f} r-adj={s['risk_adj']:.3f}")
    except Exception as e:
        log(f"  ablation hatasi: {e}")

    # Summary
    log("\n" + "=" * 110)
    log("SUMMARY")
    log("=" * 110)
    if ml_stats_list and base_stats:
        log(f"BASELINE (no ML, 3y rolling 13w):")
        log(f"  yillik {base_stats['ann_mean']:+.2f}% (min {base_stats['ann_min']:+.1f}, max {base_stats['ann_max']:+.1f})")
        log(f"  DD ort {base_stats['dd_mean']:+.1f}% (worst {base_stats['dd_min']:+.1f})  r-adj={base_stats['risk_adj']:.3f}")
        log("")
        for thr, s in ml_stats_list:
            delta_ann = s['ann_mean'] - base_stats['ann_mean']
            delta_dd = s['dd_mean'] - base_stats['dd_mean']  # negatif fark = DD daha kotu
            log(f"ML thr={thr:.2f}: yillik {s['ann_mean']:+.2f}% (delta {delta_ann:+.2f}pp), "
                f"DD {s['dd_mean']:+.1f}% (delta {delta_dd:+.1f}pp), r-adj={s['risk_adj']:.3f}")

    REPORT_OUT.parent.mkdir(parents=True, exist_ok=True)
    REPORT_OUT.write_text("\n".join(lines), encoding="utf-8")
    log(f"\nReport saved: {REPORT_OUT}")


if __name__ == "__main__":
    main()
