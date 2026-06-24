"""SEC-SCALP P1 — Vol-target 15m R4 sweep + retest.

Görev (brief):
  Step 4 — Replay parity (vol_target.enabled=false): mevcut +%735.73 baseline byte-identical
  Step 5 — Walk-forward 34 pencere + per-ay sec49 paterni vol_target=true ile
  Step 6 — target_atr_pct sweep: 0.005, 0.010, 0.015, 0.020, 0.030

Pool: data/sec31_15m_pool.pkl (TOP-10 cached) -> TOP-4 + 10 sym filter
Config: configs/risk_phoenix_scalp_15m_pyramid_r3.yaml (P0 fix applied)
Override: max_concurrent=20, same_symbol_side_cooldown_days=0  (R4 mc=20 senaryosu)

Output:
  reports/engineering/2026-05-17_vol_target_15m_r4_sweep.csv
"""
from __future__ import annotations
import csv
import io
import os
import pickle
import sys
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean

if __name__ == "__main__":
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    except Exception:
        pass

os.environ["PA_LOG_QUIET"] = "1"
import warnings
warnings.filterwarnings("ignore")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

import logging
logging.getLogger("price_action").setLevel(logging.ERROR)

import pandas as pd

CACHE = ROOT / "data" / "sec31_15m_pool.pkl"
YAML_R3 = ROOT / "configs" / "risk_phoenix_scalp_15m_pyramid_r3.yaml"
CSV_OUT = ROOT / "reports" / "engineering" / "2026-05-17_vol_target_15m_r4_sweep.csv"
CSV_MONTHS = ROOT / "reports" / "engineering" / "2026-05-17_vol_target_15m_r4_per_month.csv"

from price_action.backtest.lab import ProductionConfig, production_replay

TOP4 = {"vsa_climax_test", "brooks_failed_breakout",
        "anchored_vwap_reversal", "engulfing_continuation"}
SYMS = {"BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT", "ADA/USDT",
        "AVAX/USDT", "LINK/USDT", "DOT/USDT", "DOGE/USDT", "XRP/USDT"}

TRAIN_DAYS = 2 * 365
OOS_DAYS = 90
STEP_DAYS = 30

# Sweep grid: 0.005 (çok sıkı) -> 0.030 (gevşek)
# Mevcut YAML: 0.010
# 15m 14-bar ATR%, BTC ~0.5-1.5% normal range
SWEEP_TARGETS = [
    ("OFF", None),
    ("0.005", 0.005),
    ("0.010", 0.010),  # current YAML
    ("0.015", 0.015),
    ("0.020", 0.020),
    ("0.030", 0.030),
]


def to_utc(ts):
    if hasattr(ts, "tz_localize"):
        if ts.tzinfo is None:
            return ts.tz_localize("UTC")
        return ts.tz_convert("UTC")
    if ts.tzinfo is None:
        return ts.replace(tzinfo=timezone.utc)
    return ts.astimezone(timezone.utc)


def build_windows(pool):
    pool.sort(key=lambda x: x["entry_ts"])
    start = pool[0]["entry_ts"]
    end = pool[-1]["exit_ts"]
    out = []
    cur = start
    while cur + pd.Timedelta(days=TRAIN_DAYS + OOS_DAYS) <= end:
        out.append((cur, cur + pd.Timedelta(days=TRAIN_DAYS)))
        cur += pd.Timedelta(days=STEP_DAYS)
    return out


def run_walkforward(cfg, pool, windows, years=TRAIN_DAYS / 365.0):
    anns, dds, ras = [], [], []
    neg = 0
    n_trades_total = 0
    for ws, we in windows:
        w = [t for t in pool if ws <= t["entry_ts"] < we]
        if not w:
            continue
        r = production_replay(w, cfg)
        if r is None:
            continue
        ann = r.annualized(years) * 100
        dd = r.max_drawdown * 100
        ra = ann / abs(dd) if dd != 0 else 0
        anns.append(ann)
        dds.append(dd)
        ras.append(ra)
        n_trades_total += r.trades
        if ann < 0:
            neg += 1
    if not anns:
        return None
    return {
        "n_win": len(anns), "neg": neg,
        "ma": mean(anns), "md": mean(dds), "ra": mean(ras),
        "n_tr": n_trades_total,
    }


def run_per_month(cfg, pool, months):
    out = []
    for yr, mo, ms, me in months:
        m_trades = [t for t in pool if ms <= to_utc(t["entry_ts"]) < me]
        if len(m_trades) < 10:
            continue
        r = production_replay(m_trades, cfg)
        if r is None:
            continue
        out.append({
            "year": yr, "month": mo,
            "n_trade": len(m_trades),
            "ret_pct": r.total_return * 100,
            "dd_pct": r.max_drawdown * 100,
            "final_eq": r.final_equity,
        })
    return out


def summarize_months(month_results):
    rets = [r["ret_pct"] for r in month_results]
    if not rets:
        return None
    n = len(rets)
    mean_ret = sum(rets) / n
    if n > 1:
        std = (sum((x - mean_ret) ** 2 for x in rets) / (n - 1)) ** 0.5
    else:
        std = 0.0
    cv = std / abs(mean_ret) if mean_ret != 0 else float("inf")
    pos = sum(1 for x in rets if x > 0)
    neg = sum(1 for x in rets if x < 0)
    zero = sum(1 for x in rets if x == 0)
    ge15 = sum(1 for x in rets if x >= 15.0)
    ge20 = sum(1 for x in rets if x >= 20.0)
    return {
        "n": n,
        "mean": mean_ret, "std": std, "cv_pct": cv * 100,
        "min": min(rets), "max": max(rets),
        "pos": pos, "neg": neg, "zero": zero,
        "ge15": ge15, "ge20": ge20,
    }


def main():
    # ========================================================================
    # 1) Pool load + filter
    # ========================================================================
    print(f"[LOAD] {CACHE.name} ({CACHE.stat().st_size/1e6:.1f} MB)", flush=True)
    with CACHE.open("rb") as f:
        pool_raw = pickle.load(f)
    pool = [t for t in pool_raw
            if t.get("strategy") in TOP4 and t.get("symbol") in SYMS]
    print(f"[POOL] {len(pool):,} trade  (TOP-4 × 10 sym × 5y)", flush=True)
    pool.sort(key=lambda x: x["entry_ts"])

    # ========================================================================
    # 2) Base config (YAML load + R4 override)
    # ========================================================================
    cfg_base = ProductionConfig.from_yaml(str(YAML_R3))
    cfg_base = cfg_base.with_overrides(max_concurrent=20,
                                       same_symbol_side_cooldown_days=0)
    print(f"[YAML] {YAML_R3.name} + R4 override (mc=20, cooldown=0)", flush=True)
    print(f"   YAML vol_target_enabled={cfg_base.vol_target_enabled}, "
          f"target={cfg_base.vol_target_atr_pct}", flush=True)

    # ========================================================================
    # 3) Walk-forward windows
    # ========================================================================
    windows = build_windows(pool)
    print(f"[WINDOWS] {len(windows)} (2y train + 3mo OOS + 1mo step)", flush=True)

    # ========================================================================
    # 4) Per-month buckets
    # ========================================================================
    start_dt = to_utc(pool[0]["entry_ts"])
    end_dt = to_utc(pool[-1]["entry_ts"])
    months = []
    cur_year, cur_month = start_dt.year, start_dt.month
    while True:
        m_start = datetime(cur_year, cur_month, 1, tzinfo=timezone.utc)
        if cur_month == 12:
            m_end = datetime(cur_year + 1, 1, 1, tzinfo=timezone.utc)
        else:
            m_end = datetime(cur_year, cur_month + 1, 1, tzinfo=timezone.utc)
        if m_start > end_dt:
            break
        months.append((cur_year, cur_month, m_start, m_end))
        cur_month += 1
        if cur_month > 12:
            cur_month = 1
            cur_year += 1
    print(f"[MONTHS] {len(months)} ay bucket", flush=True)

    # ========================================================================
    # 5) Sweep loop
    # ========================================================================
    print(f"\n{'='*100}", flush=True)
    print(f"SWEEP: 6 scenario (vol_target OFF + 5 target_atr_pct)", flush=True)
    print(f"{'='*100}\n", flush=True)
    print(f"{'Label':<12} {'WF_Ann%':>10} {'WF_DD%':>9} {'WF_radj':>9} {'WF_neg':>7} {'WF_tr':>10} | "
          f"{'M_mean%':>9} {'M_std':>7} {'M_CV%':>7} {'pos':>5} {'neg':>5} {'zero':>5} {'>=15':>5} {'>=20':>5}",
          flush=True)
    print("-" * 150, flush=True)

    all_results = []
    all_month_rows = []

    for label, target in SWEEP_TARGETS:
        if target is None:
            cfg = cfg_base.with_overrides(vol_target_enabled=False)
        else:
            cfg = cfg_base.with_overrides(vol_target_enabled=True,
                                          vol_target_atr_pct=target)

        # Walk-forward
        wf = run_walkforward(cfg, pool, windows)
        # Per-month
        m_res = run_per_month(cfg, pool, months)
        m_sum = summarize_months(m_res)

        if wf is None or m_sum is None:
            print(f"{label:<12}  (REPLAY FAIL)", flush=True)
            continue

        print(
            f"{label:<12} {wf['ma']:>+9.2f}% {wf['md']:>+8.2f}% {wf['ra']:>9.3f} {wf['neg']:>7} {wf['n_tr']:>10,} | "
            f"{m_sum['mean']:>+8.2f}% {m_sum['std']:>6.1f} {m_sum['cv_pct']:>6.0f}% "
            f"{m_sum['pos']:>5} {m_sum['neg']:>5} {m_sum['zero']:>5} {m_sum['ge15']:>5} {m_sum['ge20']:>5}",
            flush=True,
        )

        all_results.append({
            "label": label,
            "target_atr_pct": target if target is not None else "",
            "wf_mean_ann_pct": wf["ma"],
            "wf_mean_dd_pct": wf["md"],
            "wf_r_adj": wf["ra"],
            "wf_n_win": wf["n_win"],
            "wf_neg": wf["neg"],
            "wf_n_trades": wf["n_tr"],
            "m_n": m_sum["n"],
            "m_mean_pct": m_sum["mean"],
            "m_std_pp": m_sum["std"],
            "m_cv_pct": m_sum["cv_pct"],
            "m_min_pct": m_sum["min"],
            "m_max_pct": m_sum["max"],
            "m_pos": m_sum["pos"],
            "m_neg": m_sum["neg"],
            "m_zero": m_sum["zero"],
            "m_ge15": m_sum["ge15"],
            "m_ge20": m_sum["ge20"],
        })
        for mr in m_res:
            all_month_rows.append({"label": label, **mr})

    # ========================================================================
    # 6) Persist CSV
    # ========================================================================
    CSV_OUT.parent.mkdir(parents=True, exist_ok=True)
    fields = list(all_results[0].keys())
    with CSV_OUT.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        for row in all_results:
            w.writerow(row)
    print(f"\n[CSV] {CSV_OUT}", flush=True)

    if all_month_rows:
        with CSV_MONTHS.open("w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=list(all_month_rows[0].keys()))
            w.writeheader()
            for row in all_month_rows:
                w.writerow(row)
        print(f"[CSV] {CSV_MONTHS}", flush=True)

    # ========================================================================
    # 7) Verdict (best by CV under mean >= 15%)
    # ========================================================================
    candidates = [r for r in all_results if r["m_mean_pct"] >= 15.0]
    if not candidates:
        print("\nVERDICT: FAIL — no scenario with mean monthly >= 15%", flush=True)
        return
    best = min(candidates, key=lambda r: r["m_cv_pct"])
    print(f"\nBEST (mean>=15%, min CV): {best['label']}", flush=True)
    print(f"  mean monthly {best['m_mean_pct']:+.2f}%  CV {best['m_cv_pct']:.0f}%  "
          f"neg {best['m_neg']}/61  pos {best['m_pos']}/61  >=20% {best['m_ge20']}/61",
          flush=True)

    if best["m_cv_pct"] <= 70 and best["m_mean_pct"] >= 20:
        v = "PASS"
    elif best["m_cv_pct"] <= 100 and best["m_mean_pct"] >= 15:
        v = "PARTIAL"
    else:
        v = "FAIL"
    print(f"VERDICT: {v}", flush=True)


if __name__ == "__main__":
    main()
