"""Yol G — Ensemble retest 15m R4 (TOP-4) + bb_band_continuation.

Post-hoc gözlemsel test: Yol G standalone border RED (5/6 PASS, WR 51.4%
vs 55%). mR +0.20, p=0.000, 3/3 regime pozitif çok güçlü sinyal. Pre-reg
disiplini gereği RED dedi ama mandate gap kapatma açısından ensemble
katkı ölçümü değerli (post-hoc, p-hacking değil — yan-bulgu observational).

Walk-forward 34-pencere + per-ay 61 ay. R4 baseline vs R4 + BB-cont karşılaştırma.

Mandate baseline (canonical SEC-S5 retest sayıları, cooldown=15dk YAML):
  Annual +%1076, Mean +%28.9, CV 144%, Zero 0, Neg 7
"""
from __future__ import annotations

import io
import os
import pickle
import sys
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean as stat_mean
from statistics import stdev

if __name__ == "__main__":
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    except Exception:
        pass

os.environ["PA_LOG_QUIET"] = "1"
import warnings
warnings.filterwarnings("ignore")
import logging
logging.getLogger("price_action").setLevel(logging.ERROR)

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

import pandas as pd

from price_action.backtest.lab import ProductionConfig, production_replay

POOL_R4 = ROOT / "data" / "sec31_15m_pool.pkl"
POOL_YOL_G = ROOT / "data" / "sec_s5_yol_g_bb_cont_v1_pool.pkl"
YAML_R3 = ROOT / "configs" / "risk_phoenix_scalp_15m_pyramid_r3.yaml"
REPORT_OUT = ROOT / "reports" / "researcher" / "2026-05-17_yol_g_ensemble_retest.md"

TOP4 = {"vsa_climax_test", "brooks_failed_breakout",
        "anchored_vwap_reversal", "engulfing_continuation"}
SYMS = {"BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT", "ADA/USDT",
        "AVAX/USDT", "LINK/USDT", "DOT/USDT", "DOGE/USDT", "XRP/USDT"}

TRAIN_DAYS = 2 * 365
OOS_DAYS = 90
STEP_DAYS = 30


def to_utc(ts):
    if hasattr(ts, "tz_localize"):
        if ts.tzinfo is None:
            return ts.tz_localize("UTC")
        return ts.tz_convert("UTC")
    if ts.tzinfo is None:
        return ts.replace(tzinfo=timezone.utc)
    return ts.astimezone(timezone.utc)


def build_windows(trades):
    trades.sort(key=lambda x: x["entry_ts"])
    start = trades[0]["entry_ts"]
    end = trades[-1]["exit_ts"]
    out = []
    cur = start
    while cur + pd.Timedelta(days=TRAIN_DAYS + OOS_DAYS) <= end:
        out.append((cur, cur + pd.Timedelta(days=TRAIN_DAYS)))
        cur += pd.Timedelta(days=STEP_DAYS)
    return out


def walk_forward(pool, cfg, years=TRAIN_DAYS / 365.0):
    pool = sorted(pool, key=lambda x: x["entry_ts"])
    windows = build_windows(pool)
    anns, dds, neg, n_trades_total = [], [], 0, 0
    for ws, we in windows:
        w = [t for t in pool if ws <= t["entry_ts"] < we]
        if not w:
            continue
        r = production_replay(w, cfg)
        if r is None:
            continue
        ann = r.annualized(years) * 100
        dd = r.max_drawdown * 100
        anns.append(ann); dds.append(dd); n_trades_total += r.trades
        if ann < 0:
            neg += 1
    if not anns:
        return None
    return {
        "n_win": len(anns), "neg": neg,
        "ann_mean": stat_mean(anns), "ann_min": min(anns), "ann_max": max(anns),
        "dd_mean": stat_mean(dds),
        "r_adj": stat_mean(anns) / abs(stat_mean(dds)) if stat_mean(dds) != 0 else 0,
        "n_trades_total": n_trades_total,
    }


def per_month(pool, cfg):
    pool = sorted(pool, key=lambda x: to_utc(x["entry_ts"]))
    start = to_utc(pool[0]["entry_ts"])
    end = to_utc(pool[-1]["entry_ts"])

    months = []
    cy, cm = start.year, start.month
    while True:
        ms = datetime(cy, cm, 1, tzinfo=timezone.utc)
        if cm == 12:
            me = datetime(cy + 1, 1, 1, tzinfo=timezone.utc)
        else:
            me = datetime(cy, cm + 1, 1, tzinfo=timezone.utc)
        if ms > end:
            break
        months.append((cy, cm, ms, me))
        cm += 1
        if cm > 12:
            cm = 1
            cy += 1

    rets = []
    zero_months = 0
    neg_months = 0
    ge20 = 0
    ge15 = 0
    for yr, mo, ms, me in months:
        m_tr = [t for t in pool if ms <= to_utc(t["entry_ts"]) < me]
        if len(m_tr) < 10:
            zero_months += 1
            rets.append(0.0)
            continue
        r = production_replay(m_tr, cfg)
        if r is None:
            rets.append(0.0)
            continue
        ret_pct = r.total_return * 100
        rets.append(ret_pct)
        if ret_pct < 0:
            neg_months += 1
        if ret_pct >= 20:
            ge20 += 1
        if ret_pct >= 15:
            ge15 += 1
    if not rets:
        return None
    mu = stat_mean(rets)
    sd = stdev(rets) if len(rets) > 1 else 0.0
    return {
        "n_months": len(months), "mean_pct": mu, "stdev_pct": sd,
        "cv_pct": (sd / abs(mu) * 100) if mu != 0 else 1e9,
        "zero_months": zero_months, "neg_months": neg_months,
        "ge20": ge20, "ge15": ge15,
        "min_pct": min(rets), "max_pct": max(rets),
    }


def scenario(name, pool, cfg, w):
    w(f"### {name}")
    w("")
    if not pool:
        w("**SKIP** (empty pool)")
        w("")
        return None
    Rs = [t["R"] for t in pool]
    w(f"- Pool size: {len(pool):,} trades, mean R {sum(Rs)/len(Rs):+.3f}, sumR {sum(Rs):+.1f}")

    print(f"  [walk-forward] {name}...")
    wf = walk_forward(pool, cfg)
    if wf is None:
        w("- Walk-forward: NO RESULT")
        return None
    w(f"- Walk-forward (34-window): annual mean **{wf['ann_mean']:+.1f}%** "
      f"(min {wf['ann_min']:+.1f}%, max {wf['ann_max']:+.1f}%)")
    w(f"- DD mean: **{wf['dd_mean']:+.1f}%**, r-adj: **{wf['r_adj']:.2f}**")
    w(f"- Positive windows: {wf['n_win'] - wf['neg']}/{wf['n_win']}, total trades: {wf['n_trades_total']:,}")

    print(f"  [per-month] {name}...")
    pm = per_month(pool, cfg)
    if pm is None:
        w("- Per-month: NO RESULT")
        return wf
    w(f"- Per-month ({pm['n_months']} months):")
    w(f"  - Mean: **{pm['mean_pct']:+.2f}%** | stdev: {pm['stdev_pct']:.2f}% | CV: **{pm['cv_pct']:.0f}%**")
    w(f"  - Zero months: **{pm['zero_months']}/{pm['n_months']}** | Neg: **{pm['neg_months']}/{pm['n_months']}**")
    w(f"  - ge20: **{pm['ge20']}/{pm['n_months']}** | ge15: **{pm['ge15']}/{pm['n_months']}**")
    w(f"  - Min/Max: {pm['min_pct']:+.2f}% / {pm['max_pct']:+.2f}%")
    w("")
    return {"wf": wf, "pm": pm, "name": name}


def main():
    REPORT_OUT.parent.mkdir(parents=True, exist_ok=True)
    out_lines: list[str] = []

    def w(line: str = ""):
        print(line)
        out_lines.append(line)

    w("# Yol G — Ensemble Retest (15m R4 + BB-Band Continuation)")
    w("")
    w(f"**Generated:** {pd.Timestamp.now('UTC').isoformat()}")
    w("**Walk-forward:** 2y train + 3mo OOS + 1mo step (34 windows)")
    w("**Post-hoc gözlemsel test** — Yol G standalone border RED (WR 51.4% gate 55%).")
    w("")
    w("## User Mandate")
    w("- Annual >= +%400")
    w("- Mean monthly >= +%20")
    w("- Zero ay <= 8")
    w("- Neg ay <= 6")
    w("- CV <= %100")
    w("")
    w("## Baseline (SEC-S5 canonical, cooldown=15dk YAML)")
    w("Annual +%1076, Mean +%28.9, Zero 0, Neg 7, CV 144%")
    w("")

    print(f"[load] {POOL_R4.name}")
    with POOL_R4.open("rb") as f:
        r4_raw = pickle.load(f)
    pool_r4 = [t for t in r4_raw if t.get("strategy") in TOP4 and t.get("symbol") in SYMS]
    print(f"  R4 (TOP-4): {len(pool_r4):,} trades")

    if not POOL_YOL_G.exists():
        print(f"ERROR: Yol G pool cache missing {POOL_YOL_G}")
        return
    print(f"[load] {POOL_YOL_G.name}")
    with POOL_YOL_G.open("rb") as f:
        yol_g_pool = pickle.load(f)
    # If dict (by_strat), extract list
    if isinstance(yol_g_pool, dict):
        yol_g_trades = []
        for k, v in yol_g_pool.items():
            print(f"  Yol G {k}: {len(v):,} trades")
            yol_g_trades.extend(v)
    else:
        yol_g_trades = yol_g_pool
        print(f"  Yol G bb_band_continuation: {len(yol_g_trades):,} trades")

    cfg = ProductionConfig.from_yaml(str(YAML_R3)).with_overrides(max_concurrent=20)
    print(f"\n[cfg] {YAML_R3.name} (mc=20, cooldown=YAML default=15dk, halt OFF YAML)")
    w(f"## Scenarios")
    w("")

    # A: Baseline R4
    res_a = scenario("A. R4 baseline (TOP-4 trend-cont only)", pool_r4, cfg, w)

    # B: R4 + Yol G BB-cont
    combined = pool_r4 + yol_g_trades
    res_b = scenario("B. R4 + bb_band_continuation (Yol G)", combined, cfg, w)

    # Mandate verdict
    if res_a and res_b:
        w("## Mandate Verdict")
        w("")
        rows = [("A. R4 baseline", res_a), ("B. R4 + Yol G", res_b)]
        w("| Scenario | Annual | DD | r-adj | Mean/mo | CV | Zero | Neg | ge20 |")
        w("|---|---:|---:|---:|---:|---:|---:|---:|---:|")
        for name, r in rows:
            wf = r["wf"]; pm = r["pm"]
            w(f"| {name} | {wf['ann_mean']:+.1f}% | {wf['dd_mean']:+.1f}% | "
              f"{wf['r_adj']:.2f} | {pm['mean_pct']:+.2f}% | {pm['cv_pct']:.0f}% | "
              f"{pm['zero_months']} | {pm['neg_months']} | {pm['ge20']} |")
        w("")
        wf_a = res_a["wf"]; pm_a = res_a["pm"]
        wf_b = res_b["wf"]; pm_b = res_b["pm"]
        w(f"### Yol G Delta (B - A):")
        w(f"- Annual: {wf_b['ann_mean'] - wf_a['ann_mean']:+.2f}pp")
        w(f"- Mean monthly: {pm_b['mean_pct'] - pm_a['mean_pct']:+.2f}pp")
        w(f"- CV: {pm_b['cv_pct'] - pm_a['cv_pct']:+.1f}pp")
        w(f"- Zero ay: {pm_b['zero_months'] - pm_a['zero_months']:+d}")
        w(f"- Neg ay: {pm_b['neg_months'] - pm_a['neg_months']:+d}")
        w(f"- ge20 ay: {pm_b['ge20'] - pm_a['ge20']:+d}")
        w(f"- r-adj: {wf_b['r_adj'] - wf_a['r_adj']:+.2f}")
        w("")
        # Mandate compliance
        passes_b = 0
        targets = [
            ("Annual >= 400%", wf_b['ann_mean'] >= 400),
            ("Mean monthly >= 20%", pm_b['mean_pct'] >= 20),
            ("Zero ay <= 8", pm_b['zero_months'] <= 8),
            ("Neg ay <= 6", pm_b['neg_months'] <= 6),
            ("CV <= 100%", pm_b['cv_pct'] <= 100),
        ]
        w("### Mandate Compliance (Scenario B)")
        for label, ok in targets:
            mark = "✅" if ok else "❌"
            if ok:
                passes_b += 1
            w(f"- {mark} {label}")
        w("")
        w(f"**Score: {passes_b}/5 PASS.**")

    REPORT_OUT.write_text("\n".join(out_lines), encoding="utf-8")
    print(f"\n[OK] {REPORT_OUT}")


if __name__ == "__main__":
    main()
