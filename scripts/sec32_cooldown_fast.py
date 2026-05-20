"""SEC32 fast — Replay parity (Run 1 vs Run 2) only. Quick sanity check.

Just runs 2 scenarios: cooldown=0.010d (YAML) vs cooldown=0.0d (override).
Skips full sweep. ~5-10 min total.
"""
from __future__ import annotations
import io, os, pickle, sys, time
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean as stat_mean, stdev

if __name__ == "__main__":
    try: sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    except Exception: pass

os.environ["PA_LOG_QUIET"] = "1"
import warnings; warnings.filterwarnings("ignore")
import logging; logging.getLogger("price_action").setLevel(logging.ERROR)

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "src"))

import pandas as pd
from price_action.backtest.lab import ProductionConfig, production_replay

POOL_R4 = ROOT / "data" / "sec31_15m_pool.pkl"
YAML_R3 = ROOT / "configs" / "risk_phoenix_scalp_15m_pyramid_r3.yaml"

TOP4 = {"vsa_climax_test", "brooks_failed_breakout",
        "anchored_vwap_reversal", "engulfing_continuation"}
SYMS = {"BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT", "ADA/USDT",
        "AVAX/USDT", "LINK/USDT", "DOT/USDT", "DOGE/USDT", "XRP/USDT"}

TRAIN_DAYS = 2 * 365
OOS_DAYS = 90
STEP_DAYS = 30


def to_utc(ts):
    return ts.replace(tzinfo=timezone.utc) if ts.tzinfo is None else ts.astimezone(timezone.utc)


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


def walk_forward(pool, cfg, years=TRAIN_DAYS/365.0):
    pool = sorted(pool, key=lambda x: x["entry_ts"])
    windows = build_windows(pool)
    anns, dds, neg, ntot = [], [], 0, 0
    for ws, we in windows:
        w = [t for t in pool if ws <= t["entry_ts"] < we]
        if not w:
            continue
        r = production_replay(w, cfg)
        if r is None:
            continue
        ann = r.annualized(years) * 100
        dd = r.max_drawdown * 100
        anns.append(ann); dds.append(dd); ntot += r.trades
        if ann < 0: neg += 1
    if not anns:
        return None
    ma = stat_mean(anns); md = stat_mean(dds)
    return {"n_win": len(anns), "neg": neg, "ann_mean": ma, "ann_min": min(anns),
            "ann_max": max(anns), "dd_mean": md,
            "r_adj": ma / abs(md) if md != 0 else 0, "n_trades_total": ntot}


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
            cm = 1; cy += 1

    rets, zero, neg, ge20 = [], 0, 0, 0
    for yr, mo, ms, me in months:
        m_tr = [t for t in pool if ms <= to_utc(t["entry_ts"]) < me]
        if len(m_tr) < 1:
            zero += 1; rets.append(0.0); continue
        if len(m_tr) < 10:
            rets.append(0.0); continue
        r = production_replay(m_tr, cfg)
        if r is None:
            rets.append(0.0); continue
        ret = r.total_return * 100
        rets.append(ret)
        if ret < 0: neg += 1
        if ret >= 20.0: ge20 += 1
    if not rets:
        return None
    mu = stat_mean(rets)
    sd = stdev(rets) if len(rets) > 1 else 0.0
    return {"n_months": len(months), "mean_pct": mu, "stdev_pct": sd,
            "cv_pct": (sd / abs(mu) * 100) if mu != 0 else 1e9,
            "zero_months": zero, "neg_months": neg, "ge20_months": ge20,
            "min_pct": min(rets), "max_pct": max(rets)}


def run(cd_label, cd_val, pool, base_cfg):
    t0 = time.time()
    print(f"\n>>> COOLDOWN = {cd_val:.4f}d  ({cd_label})", flush=True)
    cfg = base_cfg.with_overrides(same_symbol_side_cooldown_days=cd_val)
    print("  walk_forward...", flush=True)
    wf = walk_forward(pool, cfg)
    print(f"    WF done in {time.time()-t0:.1f}s: ann_mean={wf['ann_mean']:+.1f}% trades={wf['n_trades_total']:,}", flush=True)
    t1 = time.time()
    print("  per_month...", flush=True)
    pm = per_month(pool, cfg)
    print(f"    PM done in {time.time()-t1:.1f}s: mean={pm['mean_pct']:+.2f}% CV={pm['cv_pct']:.0f}% zero={pm['zero_months']} neg={pm['neg_months']} ge20={pm['ge20_months']}", flush=True)
    return {"label": cd_label, "cd": cd_val, "wf": wf, "pm": pm}


def main():
    t_start = time.time()
    print(f"[load] {POOL_R4.name}", flush=True)
    with POOL_R4.open("rb") as f:
        r4 = pickle.load(f)
    pool = [t for t in r4 if t.get("strategy") in TOP4 and t.get("symbol") in SYMS]
    print(f"  TOP-4 pool: {len(pool):,}", flush=True)

    base_cfg = ProductionConfig.from_yaml(str(YAML_R3)).with_overrides(max_concurrent=20)
    print(f"[cfg] cooldown YAML default = {base_cfg.same_symbol_side_cooldown_days}d", flush=True)

    results = []
    # Run 1: YAML (0.010 = 15dk)
    results.append(run("0.010d 15dk YAML", 0.010, pool, base_cfg))
    # Run 2: 0
    results.append(run("0.0d RESUME override", 0.0, pool, base_cfg))

    print(f"\n=== SUMMARY ===", flush=True)
    print(f"{'label':<28} | {'annual':>8} | {'mean/mo':>8} | {'CV':>6} | {'zero':>4} | {'neg':>4} | {'ge20':>4} | {'WFtrades':>10}", flush=True)
    for r in results:
        print(f"{r['label']:<28} | {r['wf']['ann_mean']:>+7.1f}% | {r['pm']['mean_pct']:>+7.2f}% | {r['pm']['cv_pct']:>5.0f}% | {r['pm']['zero_months']:>4d} | {r['pm']['neg_months']:>4d} | {r['pm']['ge20_months']:>4d} | {r['wf']['n_trades_total']:>10,}", flush=True)

    a, b = results[0], results[1]
    print(f"\n=== DELTA (Run1 15dk - Run2 0) ===", flush=True)
    print(f"  annual:  {a['wf']['ann_mean']-b['wf']['ann_mean']:+.1f}pp", flush=True)
    print(f"  mean/mo: {a['pm']['mean_pct']-b['pm']['mean_pct']:+.2f}pp", flush=True)
    print(f"  CV:      {a['pm']['cv_pct']-b['pm']['cv_pct']:+.0f}pp", flush=True)
    print(f"  zero:    {a['pm']['zero_months']-b['pm']['zero_months']:+d}", flush=True)
    print(f"  neg:     {a['pm']['neg_months']-b['pm']['neg_months']:+d}", flush=True)
    print(f"  ge20:    {a['pm']['ge20_months']-b['pm']['ge20_months']:+d}", flush=True)
    print(f"  WFtrades: {a['wf']['n_trades_total']-b['wf']['n_trades_total']:+,}", flush=True)

    print(f"\nTotal time: {time.time()-t_start:.1f}s", flush=True)

    # Save raw
    import json
    out_path = ROOT / "data" / "sec32_cooldown_fast_results.json"
    with out_path.open("w", encoding="utf-8") as f:
        json.dump([{
            "label": r["label"], "cd": r["cd"],
            "wf": {k: v for k, v in r["wf"].items()},
            "pm": {k: v for k, v in r["pm"].items()},
        } for r in results], f, indent=2)
    print(f"[saved] {out_path}", flush=True)


if __name__ == "__main__":
    main()
