"""ML Meta-Labeling v1 — SECTION 2: Trade pool + feature/label baseline raporu.

Pre-reg: memory/researcher/hypotheses/2026-05-15-ml-meta-labeling-v1.md

Bu script SADECE veri quality + go/no-go raporu uretir. ML modeli egitmez.

Cikti:
  - 4787 trade pool dogrulama
  - Triple-barrier label dagilimi (per symbol + global)
  - Strategy R-based label dagilimi (gercek backtest sonuclari)
  - Concordance: triple-barrier vs strategy
  - Feature matrix dist: NaN sayimi, range, simetri
  - 13 walk-forward pencere icin train/oos boyutlari
  - Per-symbol class balance

Output: reports/research/ml_meta_v1_baseline.txt
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

from price_action.ml.meta_labeling import (
    triple_barrier_labels,
    engineer_features,
)

TRADES_CACHE = ROOT / "data" / "v095_trades_cache.pkl"
OHLCV_CACHE = ROOT / "data" / "v095_ohlcv_cache.pkl"
REPORT_OUT = ROOT / "reports" / "research" / "ml_meta_v1_baseline.txt"


def load_trades() -> list[dict]:
    if not TRADES_CACHE.exists():
        raise FileNotFoundError(
            f"{TRADES_CACHE} bulunamadi. Once scripts/v095_ml_trade_scoring.py'yi calistirin (cache uretmek icin)."
        )
    with TRADES_CACHE.open("rb") as f:
        return pickle.load(f)


def load_ohlcv() -> dict[str, pd.DataFrame]:
    if not OHLCV_CACHE.exists():
        raise FileNotFoundError(
            f"{OHLCV_CACHE} bulunamadi. Once scripts/v095_ml_trade_scoring.py'yi calistirin."
        )
    with OHLCV_CACHE.open("rb") as f:
        return pickle.load(f)


def trade_to_meta_signal(t: dict) -> dict:
    """v095 trade format -> meta_labeling signal format.

    Onemli: meta_labeling sig_ts = SIGNAL bar (entry bar'in 1 bar oncesi).
    v095 entry_ts = entry bar (decision bir gun once verildi varsayimi 1d data icin).

    Causality: feature engineering sig_ts AT bar yapilir, entry sig_ts+1 acilis.
    Bu mantikla sig_ts = entry_ts - 1 day yapariz.
    """
    sig_ts = pd.Timestamp(t["entry_ts"]) - pd.Timedelta(days=1)
    direction = str(t["side"]).lower()
    entry_price = float(t["entry_price"])
    sl_price = float(t["initial_sl"])
    # TP price: pre-reg atr_mult_tp=2.0 ile triple-barrier hesaplayacak,
    # ama biz ham R'yi de saklamak icin signal'a tasiriz.
    return {
        "ts": sig_ts,
        "direction": direction,
        "entry_price": entry_price,
        "sl_price": sl_price,
        "tp_price": None,  # triple_barrier_labels otomatik atr_mult_tp ile hesaplar
        "confluence_score": float(t.get("conf", 0.0)),
        "vol_z": float(t.get("vol_z", 0.0)),
        "symbol": t["symbol"],
        "strategy": t["strategy"],
        "R_realized": float(t["R"]),
        "exit_ts": pd.Timestamp(t["exit_ts"]),
        "metadata": {"near_sr": False},
    }


def normalize_ohlcv(df_in: pd.DataFrame) -> pd.DataFrame:
    """v095 ohlcv format (ts_date index) -> meta_labeling format (ts column)."""
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
    return df


def main() -> None:
    REPORT_OUT.parent.mkdir(parents=True, exist_ok=True)
    out_lines: list[str] = []

    def w(line: str = "") -> None:
        print(line)
        out_lines.append(line)

    w("=" * 78)
    w("ML META-LABELING v1 — SECTION 2 BASELINE RAPORU")
    w("=" * 78)
    w(f"Pre-reg: memory/researcher/hypotheses/2026-05-15-ml-meta-labeling-v1.md")
    w(f"Generated: {pd.Timestamp.utcnow().isoformat()}")
    w("")

    # 1) Trade pool
    w("--- 1) TRADE POOL ---")
    trades = load_trades()
    n = len(trades)
    w(f"Toplam trade: {n}")
    df_trades = pd.DataFrame(trades)
    df_trades["entry_ts"] = pd.to_datetime(df_trades["entry_ts"], utc=True)
    df_trades["exit_ts"] = pd.to_datetime(df_trades["exit_ts"], utc=True)
    w(f"Tarih araligi: {df_trades['entry_ts'].min()} -> {df_trades['entry_ts'].max()}")

    by_strat = df_trades["strategy"].value_counts()
    w(f"Strateji sayisi: {len(by_strat)}")
    w("Per-strategy trade count:")
    for s, c in by_strat.items():
        w(f"  {s:35s} {c:>5d}")

    by_sym = df_trades["symbol"].value_counts()
    w(f"\nSembol sayisi: {len(by_sym)}")
    w("Per-symbol trade count:")
    for s, c in by_sym.items():
        w(f"  {s:15s} {c:>5d}")

    w(f"\nSide dagilimi: {df_trades['side'].value_counts().to_dict()}")

    # 2) Strategy R-based label (gercek backtest sonuclari)
    w("\n--- 2) STRATEJI R-BASED LABEL DAGILIMI ---")
    df_trades["y_strategy"] = (df_trades["R"] > 0).astype(int)
    y_strat_mean = df_trades["y_strategy"].mean()
    w(f"Win rate (R > 0): {y_strat_mean:.4f}")
    w(f"Win count: {int(df_trades['y_strategy'].sum())} / {n}")
    w(f"R dagilimi: mean={df_trades['R'].mean():+.4f}, std={df_trades['R'].std():.4f}")
    w(f"R quantiles: q05={df_trades['R'].quantile(0.05):+.3f}, "
      f"q50={df_trades['R'].quantile(0.50):+.3f}, q95={df_trades['R'].quantile(0.95):+.3f}")

    # 3) Triple-barrier label per symbol
    w("\n--- 3) TRIPLE-BARRIER LABEL DAGILIMI (atr_mult_tp=2.0, atr_mult_sl=1.0, max_hold=20) ---")
    ohlcv = load_ohlcv()
    w(f"OHLCV cache sembolleri: {len(ohlcv)}")

    all_labels: list[pd.DataFrame] = []
    per_sym_label_summary: list[dict] = []

    for sym, df_sym_raw in ohlcv.items():
        df_sym = normalize_ohlcv(df_sym_raw)
        sym_trades = df_trades[df_trades["symbol"] == sym]
        if sym_trades.empty:
            continue
        signals = [trade_to_meta_signal(t) for t in sym_trades.to_dict("records")]
        try:
            labels = triple_barrier_labels(
                df_sym,
                signals,
                atr_mult_tp=2.0,
                atr_mult_sl=1.0,
                max_holding=20,
                atr_col="atr14",
            )
        except Exception as e:
            w(f"  [WARN] {sym}: triple_barrier hatasi {e}")
            continue
        if labels.empty:
            continue
        labels["symbol"] = sym
        all_labels.append(labels)
        n_sym = len(labels)
        n_tp = int((labels["label"] == 1).sum())
        n_sl = int((labels["label"] == -1).sum())
        n_to = int((labels["label"] == 0).sum())
        per_sym_label_summary.append({
            "symbol": sym,
            "n": n_sym,
            "tp_pct": n_tp / n_sym * 100,
            "sl_pct": n_sl / n_sym * 100,
            "timeout_pct": n_to / n_sym * 100,
            "mean_holding": float(labels["holding_bars"].mean()),
        })

    if not all_labels:
        w("HATA: Hicbir sembolde triple_barrier label uretilemedi.")
        REPORT_OUT.write_text("\n".join(out_lines), encoding="utf-8")
        return

    df_labels = pd.concat(all_labels, ignore_index=True)
    n_labeled = len(df_labels)
    n_tp = int((df_labels["label"] == 1).sum())
    n_sl = int((df_labels["label"] == -1).sum())
    n_to = int((df_labels["label"] == 0).sum())
    w(f"Toplam label uretilen: {n_labeled} / {n}")
    w(f"  TP (+1):     {n_tp:>5d}  ({n_tp/n_labeled*100:.2f}%)")
    w(f"  SL (-1):     {n_sl:>5d}  ({n_sl/n_labeled*100:.2f}%)")
    w(f"  Timeout (0): {n_to:>5d}  ({n_to/n_labeled*100:.2f}%)")
    w(f"Binary y (TP=1, else=0) mean: {(df_labels['label'] == 1).mean():.4f}")
    w(f"Mean holding bars: {df_labels['holding_bars'].mean():.2f}")

    # KH-3 gate kontrolu (class balance 0.30-0.70)
    y_tb_mean = float((df_labels["label"] == 1).mean())
    if 0.30 <= y_tb_mean <= 0.70:
        w(f"[KH-3 GATE PASS] Class balance {y_tb_mean:.3f} in [0.30, 0.70]")
    else:
        w(f"[KH-3 GATE WARN] Class balance {y_tb_mean:.3f} out of [0.30, 0.70] - SMOTE veya class_weight gerekebilir")

    # Per-symbol breakdown
    w("\nPer-symbol triple-barrier breakdown:")
    w(f"  {'symbol':<15s} {'n':>5s} {'tp%':>6s} {'sl%':>6s} {'to%':>6s} {'hold':>6s}")
    for r in per_sym_label_summary:
        w(f"  {r['symbol']:<15s} {r['n']:>5d} {r['tp_pct']:>6.2f} {r['sl_pct']:>6.2f} {r['timeout_pct']:>6.2f} {r['mean_holding']:>6.2f}")

    # 4) Concordance: triple-barrier vs strategy R-label
    w("\n--- 4) CONCORDANCE: TRIPLE-BARRIER vs STRATEJI R-LABEL ---")
    # Eslestir signal_ts + symbol uzerinden
    df_labels["signal_ts"] = pd.to_datetime(df_labels["signal_ts"], utc=True)
    df_trades_idx = df_trades.copy()
    df_trades_idx["signal_ts"] = df_trades_idx["entry_ts"] - pd.Timedelta(days=1)
    merged = df_labels.merge(
        df_trades_idx[["signal_ts", "symbol", "y_strategy", "R"]],
        on=["signal_ts", "symbol"],
        how="inner",
        suffixes=("_tb", "_strat"),
    )
    n_match = len(merged)
    w(f"Eslestirilen trade: {n_match}")
    if n_match > 0:
        merged["y_tb"] = (merged["label"] == 1).astype(int)
        agree = (merged["y_tb"] == merged["y_strategy"]).mean()
        w(f"Agreement (y_tb == y_strategy): {agree:.4f}")
        # 2x2 confusion
        w("Confusion matrix (y_strategy x y_tb):")
        cm = pd.crosstab(merged["y_strategy"], merged["y_tb"])
        w(f"  {cm}")

    # 5) Feature engineering dist
    w("\n--- 5) FEATURE MATRIX DIST ---")
    all_feats: list[pd.DataFrame] = []
    for sym, df_sym_raw in ohlcv.items():
        df_sym = normalize_ohlcv(df_sym_raw)
        sym_trades = df_trades[df_trades["symbol"] == sym]
        if sym_trades.empty:
            continue
        signals = [trade_to_meta_signal(t) for t in sym_trades.to_dict("records")]
        try:
            feats = engineer_features(df_sym, signals)
        except Exception as e:
            w(f"  [WARN] {sym}: engineer_features hatasi {e}")
            continue
        if feats.empty:
            continue
        feats["symbol"] = sym
        all_feats.append(feats)

    if not all_feats:
        w("HATA: Hicbir feature uretilemedi.")
    else:
        df_feats = pd.concat(all_feats, ignore_index=False)
        w(f"Toplam feature row: {len(df_feats)}")
        w(f"Feature kolonlari ({len(df_feats.columns)}): {list(df_feats.columns)}")
        feat_cols = [c for c in df_feats.columns if c not in ["direction", "symbol"]]
        w(f"\nNumeric feature istatistikleri:")
        w(f"  {'feature':<25s} {'mean':>10s} {'std':>10s} {'min':>10s} {'max':>10s} {'nan%':>6s}")
        for c in feat_cols:
            v = pd.to_numeric(df_feats[c], errors="coerce")
            nan_pct = v.isna().mean() * 100
            w(f"  {c:<25s} {v.mean():>10.4f} {v.std():>10.4f} {v.min():>10.4f} {v.max():>10.4f} {nan_pct:>6.2f}")

    # 6) Walk-forward pencere boyutlari (13 pencere)
    w("\n--- 6) WALK-FORWARD PENCERE BOYUTLARI (13 pencere) ---")
    df_trades_sorted = df_trades.sort_values("entry_ts").reset_index(drop=True)
    t_start = df_trades_sorted["entry_ts"].min()
    t_end = df_trades_sorted["entry_ts"].max()
    w(f"Pool araligi: {t_start} -> {t_end}")
    train_y = 3
    oos_mo = 6
    step_mo = 3
    # Pencere baslangici train basi: t_start, train end: t_start+3y, oos end: train_end+6mo
    windows = []
    cur = t_start
    while True:
        train_end = cur + pd.DateOffset(years=train_y)
        oos_end = train_end + pd.DateOffset(months=oos_mo)
        if oos_end > t_end:
            break
        n_train = ((df_trades_sorted["entry_ts"] >= cur) & (df_trades_sorted["entry_ts"] < train_end)).sum()
        n_oos = ((df_trades_sorted["entry_ts"] >= train_end) & (df_trades_sorted["entry_ts"] < oos_end)).sum()
        windows.append({
            "idx": len(windows) + 1,
            "train_start": cur,
            "train_end": train_end,
            "oos_end": oos_end,
            "n_train": int(n_train),
            "n_oos": int(n_oos),
        })
        cur = cur + pd.DateOffset(months=step_mo)
    w(f"Hesaplanan pencere sayisi: {len(windows)} (target=13)")
    w(f"  {'#':>3s} {'train_start':<12s} {'train_end':<12s} {'oos_end':<12s} {'n_train':>8s} {'n_oos':>6s}")
    for ww in windows:
        w(f"  {ww['idx']:>3d} "
          f"{ww['train_start'].strftime('%Y-%m-%d'):<12s} "
          f"{ww['train_end'].strftime('%Y-%m-%d'):<12s} "
          f"{ww['oos_end'].strftime('%Y-%m-%d'):<12s} "
          f"{ww['n_train']:>8d} {ww['n_oos']:>6d}")

    # 7) Go/No-Go Karari
    w("\n--- 7) GO/NO-GO KARARI ---")
    n_train_min = min(w_["n_train"] for w_ in windows) if windows else 0
    n_oos_min = min(w_["n_oos"] for w_ in windows) if windows else 0
    w(f"Min n_train per window: {n_train_min}")
    w(f"Min n_oos per window: {n_oos_min}")
    blockers: list[str] = []
    if len(windows) < 13:
        blockers.append(f"Pencere sayisi {len(windows)} < 13 (CEO standart)")
    if n_train_min < 100:
        blockers.append(f"Min n_train {n_train_min} < 100 (RF egitimi icin yetersiz olabilir)")
    if n_oos_min < 30:
        blockers.append(f"Min n_oos {n_oos_min} < 30 (Sharpe hesabi noisy)")
    if not (0.30 <= y_tb_mean <= 0.70):
        blockers.append(f"Class balance {y_tb_mean:.3f} unbalanced — class_weight balanced critical")
    if n_labeled < n * 0.95:
        blockers.append(f"Label coverage {n_labeled}/{n} = {n_labeled/n*100:.1f}% (>=%95 hedef)")

    if blockers:
        w("BLOCKERS:")
        for b in blockers:
            w(f"  [X] {b}")
        w("\nKARAR: Devam edilebilir, ama yukaridaki uyarilara dikkat. SECTION 3 walk-forward riskli olabilir.")
    else:
        w("Tum kontroller PASS. SECTION 3 walk-forward'a gecilebilir.")
        w("\nKARAR: GO [OK]")

    REPORT_OUT.write_text("\n".join(out_lines), encoding="utf-8")
    w(f"\nRapor kaydedildi: {REPORT_OUT}")


if __name__ == "__main__":
    main()
