"""W3 Regime Forensics — ML v1 RED postmortem ipucu inceleme.

ML Meta-Labeling v1.1 walk-forward sonuclari:
  W1: alpha=-0.635 p=0.575
  W2: alpha=-2.237 p=0.795
  W3: alpha=+5.204 p=0.020  <-- TEK SIGNAL
  W4: alpha=-0.255 p=0.320
  W5: alpha=+1.376 p=0.260
  W6: alpha=+1.407 p=0.395

W3 OOS donemi: 2024-11-15 -> 2025-05-15. Bu donemde BTC'nin ne ozellikleri
diger pencerelerden farkli? Regime imzasi cikarmaya calisiyoruz.

Hesaplananlar (her pencere OOS donemi icin, BTC 1d data):
  - ATR% mean
  - EMA200 streak mean (kac gun ust uste EMA200 ustunde)
  - 90d drawdown min (en kotu donem)
  - return_30d mean
  - Volatilite rejimi (low/high)
  - Trend strength (Kaufman ER)

Output: reports/research/w3_forensics.txt
"""
from __future__ import annotations

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

OHLCV_CACHE = ROOT / "data" / "v095_ohlcv_cache.pkl"
REPORT_OUT = ROOT / "reports" / "research" / "w3_forensics.txt"

WINDOWS = [
    {"idx": 1, "oos_start": "2024-05-15", "oos_end": "2024-11-15"},
    {"idx": 2, "oos_start": "2024-08-15", "oos_end": "2025-02-15"},
    {"idx": 3, "oos_start": "2024-11-15", "oos_end": "2025-05-15"},  # OUTLIER
    {"idx": 4, "oos_start": "2025-02-15", "oos_end": "2025-08-15"},
    {"idx": 5, "oos_start": "2025-05-15", "oos_end": "2025-11-15"},
    {"idx": 6, "oos_start": "2025-08-15", "oos_end": "2026-02-15"},
]

ML_RESULTS = {
    1: {"alpha": -0.635, "p": 0.575},
    2: {"alpha": -2.237, "p": 0.795},
    3: {"alpha": +5.204, "p": 0.020},
    4: {"alpha": -0.255, "p": 0.320},
    5: {"alpha": +1.376, "p": 0.260},
    6: {"alpha": +1.407, "p": 0.395},
}


def load_btc() -> pd.DataFrame:
    with OHLCV_CACHE.open("rb") as f:
        d = pickle.load(f)
    btc = d["BTC/USDT"].copy()
    if btc.index.name == "ts_date":
        btc = btc.reset_index()
        btc["ts"] = pd.to_datetime(btc["ts_date"], utc=True)
    elif "ts" in btc.columns:
        btc["ts"] = pd.to_datetime(btc["ts"], utc=True)
    return btc.sort_values("ts").reset_index(drop=True)


def compute_window_stats(btc: pd.DataFrame, oos_start: pd.Timestamp, oos_end: pd.Timestamp) -> dict:
    """Pencere OOS doneminde BTC istatistikleri."""
    mask = (btc["ts"] >= oos_start) & (btc["ts"] < oos_end)
    sub = btc[mask].copy()
    if sub.empty:
        return {}

    # ATR% (mevcut cache'de var)
    atr_pct_col = "atr_pct" if "atr_pct" in sub.columns else None
    if atr_pct_col:
        atr_mean = float(sub["atr_pct"].mean())
        atr_med = float(sub["atr_pct"].median())
    else:
        # Compute from OHLC
        high, low, close = sub["high"], sub["low"], sub["close"]
        prev_close = close.shift(1)
        tr = pd.concat([(high-low).abs(), (high-prev_close).abs(), (low-prev_close).abs()], axis=1).max(axis=1)
        atr14 = tr.rolling(14).mean()
        atr_pct = (atr14 / close) * 100
        atr_mean = float(atr_pct.mean())
        atr_med = float(atr_pct.median())

    # EMA200 streak (mevcut cache'de var)
    if "ema200_streak" in sub.columns:
        streak_mean = float(sub["ema200_streak"].mean())
        streak_med = float(sub["ema200_streak"].median())
    else:
        ema200 = sub["close"].ewm(span=200, adjust=False).mean()
        above = (sub["close"] > ema200).astype(int)
        # streak hesabi
        streaks = []
        cur = 0
        for v in above:
            if v == 1:
                cur = cur + 1 if cur >= 0 else 1
            else:
                cur = cur - 1 if cur <= 0 else -1
            streaks.append(cur)
        streak_mean = float(np.mean(streaks))
        streak_med = float(np.median(streaks))

    # 90d drawdown
    if "dd_90d" in sub.columns:
        dd_min = float(sub["dd_90d"].min())
        dd_mean = float(sub["dd_90d"].mean())
    else:
        roll_max = sub["close"].rolling(90, min_periods=10).max()
        dd = (sub["close"] / roll_max - 1.0) * 100
        dd_min = float(dd.min())
        dd_mean = float(dd.mean())

    # Return 30d
    if "ret_30" in sub.columns:
        ret30_mean = float(sub["ret_30"].mean())
        ret30_med = float(sub["ret_30"].median())
    else:
        ret30 = sub["close"].pct_change(30) * 100
        ret30_mean = float(ret30.mean())
        ret30_med = float(ret30.median())

    # Realized volatility (close returns std)
    rets = sub["close"].pct_change()
    rv_30 = float(rets.rolling(30).std().mean() * np.sqrt(365) * 100) if len(rets) > 30 else 0.0
    rv_total = float(rets.std() * np.sqrt(365) * 100)

    # Donem total return
    if len(sub) >= 2:
        period_ret = float((sub["close"].iloc[-1] / sub["close"].iloc[0] - 1) * 100)
    else:
        period_ret = 0.0

    # Above EMA200 fraction (bull dominance)
    ema200 = sub["close"].ewm(span=200, adjust=False).mean()
    above_frac = float((sub["close"] > ema200).mean() * 100)

    # Up days fraction
    up_days_frac = float((rets > 0).mean() * 100)

    return {
        "n_bars": len(sub),
        "period_ret_pct": period_ret,
        "atr_pct_mean": atr_mean,
        "atr_pct_median": atr_med,
        "ema200_streak_mean": streak_mean,
        "ema200_streak_median": streak_med,
        "above_ema200_pct": above_frac,
        "dd_90d_min": dd_min,
        "dd_90d_mean": dd_mean,
        "ret_30d_mean_pct": ret30_mean,
        "ret_30d_median_pct": ret30_med,
        "rv_30d_annual_pct": rv_30,
        "rv_total_annual_pct": rv_total,
        "up_days_pct": up_days_frac,
    }


def main() -> None:
    REPORT_OUT.parent.mkdir(parents=True, exist_ok=True)
    out_lines: list[str] = []

    def w(line: str = "") -> None:
        print(line)
        out_lines.append(line)

    w("=" * 90)
    w("W3 REGIME FORENSICS — ML v1.1 RED postmortem")
    w("=" * 90)
    w(f"Generated: {pd.Timestamp.utcnow().isoformat()}")
    w("Hipotez: W3 (alpha +5.2, p=0.020) tek pencere signal — regime-spesifik mi?")
    w("")

    btc = load_btc()
    w(f"BTC OHLCV pool: {btc['ts'].min()} -> {btc['ts'].max()} ({len(btc)} bar)")
    w("")

    rows: list[dict] = []
    for ww in WINDOWS:
        os_s = pd.Timestamp(ww["oos_start"], tz="UTC")
        os_e = pd.Timestamp(ww["oos_end"], tz="UTC")
        stats = compute_window_stats(btc, os_s, os_e)
        stats["idx"] = ww["idx"]
        stats["oos_start"] = ww["oos_start"]
        stats["oos_end"] = ww["oos_end"]
        stats["ml_alpha"] = ML_RESULTS[ww["idx"]]["alpha"]
        stats["ml_p"] = ML_RESULTS[ww["idx"]]["p"]
        rows.append(stats)

    df = pd.DataFrame(rows)
    df_show = df[[
        "idx", "oos_start", "oos_end", "n_bars",
        "ml_alpha", "ml_p",
        "period_ret_pct", "above_ema200_pct",
        "atr_pct_mean", "ema200_streak_mean",
        "dd_90d_min", "ret_30d_mean_pct",
        "rv_30d_annual_pct", "up_days_pct",
    ]].copy()

    w("PER-WINDOW OOS BTC ISTATISTIKLERI:")
    w("")
    w(f"{'W':>2} {'oos_start':<12} {'oos_end':<12} {'alpha':>7} {'p':>5} | "
      f"{'period%':>8} {'above%':>7} {'atr%':>5} {'streak':>7} {'dd90':>7} {'ret30':>7} {'rv30':>6} {'up%':>5}")
    for _, r in df_show.iterrows():
        marker = " <--" if r["idx"] == 3 else ""
        w(f"{int(r['idx']):>2} {r['oos_start']:<12} {r['oos_end']:<12} "
          f"{r['ml_alpha']:>+7.3f} {r['ml_p']:>5.3f} | "
          f"{r['period_ret_pct']:>+8.2f} {r['above_ema200_pct']:>7.1f} "
          f"{r['atr_pct_mean']:>5.2f} {r['ema200_streak_mean']:>+7.1f} "
          f"{r['dd_90d_min']:>+7.2f} {r['ret_30d_mean_pct']:>+7.2f} "
          f"{r['rv_30d_annual_pct']:>6.1f} {r['up_days_pct']:>5.1f}{marker}")

    # W3 vs digerleri karsilastirma
    w("")
    w("--- W3 vs DIGER 5 PENCERE (mean / std / W3 z-score) ---")
    metrics = ["period_ret_pct", "above_ema200_pct", "atr_pct_mean",
               "ema200_streak_mean", "dd_90d_min", "ret_30d_mean_pct",
               "rv_30d_annual_pct", "up_days_pct"]
    w(f"  {'metric':<25} {'W3 value':>10} {'others mean':>12} {'others std':>11} {'W3 z':>7}")
    w_outlier_metrics: list[tuple[str, float, float]] = []
    for m in metrics:
        w3_val = float(df[df["idx"] == 3][m].values[0])
        others = df[df["idx"] != 3][m].values
        others_mean = float(np.mean(others))
        others_std = float(np.std(others))
        z = (w3_val - others_mean) / max(others_std, 1e-6)
        marker = " <-- OUTLIER" if abs(z) >= 1.5 else ""
        w(f"  {m:<25} {w3_val:>10.3f} {others_mean:>12.3f} {others_std:>11.3f} {z:>+7.2f}{marker}")
        if abs(z) >= 1.5:
            w_outlier_metrics.append((m, w3_val, z))

    # Spearman: ml_alpha vs her metric
    w("")
    w("--- ML ALPHA vs REGIME METRIC KORELASYON (Spearman, n=6) ---")
    w(f"  {'metric':<25} {'spearman r':>11}")
    from scipy.stats import spearmanr
    correlations: list[tuple[str, float]] = []
    for m in metrics:
        try:
            r_val, _ = spearmanr(df[m].values, df["ml_alpha"].values)
            correlations.append((m, float(r_val)))
            w(f"  {m:<25} {r_val:>+11.3f}")
        except Exception:
            pass

    # En guclu korelasyonlar
    correlations.sort(key=lambda x: abs(x[1]), reverse=True)
    w("")
    w("--- Top-3 strongest correlations (regime imzasi adaylari) ---")
    for m, r in correlations[:3]:
        w(f"  {m:<25} r={r:+.3f}")

    # Sonuc
    w("")
    w("--- SONUC ---")
    if w_outlier_metrics:
        w("W3'u ayiran z-score >=1.5 metrikler:")
        for m, v, z in w_outlier_metrics:
            w(f"  {m}: W3={v:.3f} (z={z:+.2f})")
    else:
        w("W3'u istatistiksel olarak ayiran metrik YOK (z<1.5 hepsi).")
        w("Bu W3 outlier'in regime-bazli olmadigini, sansla cikmis olabilecegini gosterir.")

    w("")
    w("HYP-2026-05-16 onerisi:")
    if w_outlier_metrics or any(abs(r) >= 0.7 for _, r in correlations):
        w("  REGIME IMZASI VAR — regime-conditional ML pre-reg yazilabilir")
    else:
        w("  REGIME IMZASI YOK (tum z<1.5 ve max |spearman|<0.7) — regime-conditional ML olasilikli")
        w("  cunku W3 outlier sansa atfedilebilir (1/6 = 0.167 random ihtimal).")
        w("  YINE DE pre-reg yazilabilir (en guclu spearman metrigi mask) — ama beklenti dusuk.")

    REPORT_OUT.write_text("\n".join(out_lines), encoding="utf-8")
    w(f"\nRapor: {REPORT_OUT}")


if __name__ == "__main__":
    main()
