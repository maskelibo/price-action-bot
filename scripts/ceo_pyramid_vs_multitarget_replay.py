"""CEO sprint — Pyramid vs Multi-Target conflict: A-F senaryo replay.

Pool: data/sec53_15m_pool_v11.pkl (AVWAP v1.1 C2+V5 champion pool)
Config: configs/risk_phoenix_scalp_15m_c2v5_final.yaml

Senaryolar:
  F: pyramid OFF (baseline)
  CURRENT: pyramid ON triggers=[1.0,1.5] sizes=[0.50,0.30] (mevcut canli)
  E: pyramid trigger ayrimi [2.0,3.0] (hasat bolgesi ustu)
  C: pyramid sizes kucult — runner-bucket proxy [0.25,0.15]
  E2: trigger [2.5,3.5]
Her senaryo: per-month (61 ay) + walk-forward (2y train / 90d OOS / 30d step).
fee=0 (YAML default) ve fee=+8 (realistik worst-case) iki kosu.
"""
from __future__ import annotations
import io, os, pickle, sys, statistics
from datetime import datetime, timezone, timedelta
from pathlib import Path

try: sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
except Exception: pass
os.environ["PA_LOG_QUIET"] = "1"
import warnings; warnings.filterwarnings("ignore")
import logging; logging.getLogger("price_action").setLevel(logging.ERROR)

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "src"))
from price_action.backtest.lab import ProductionConfig, production_replay

POOL = ROOT / "data" / "sec53_15m_pool_v11.pkl"
YAML = ROOT / "configs" / "risk_phoenix_scalp_15m_c2v5_final.yaml"


def to_utc(ts):
    return ts.replace(tzinfo=timezone.utc) if ts.tzinfo is None else ts.astimezone(timezone.utc)


def per_month(pool, cfg):
    pool = sorted(pool, key=lambda x: to_utc(x["entry_ts"]))
    start, end = to_utc(pool[0]["entry_ts"]), to_utc(pool[-1]["entry_ts"])
    months = []
    cy, cm = start.year, start.month
    while True:
        ms = datetime(cy, cm, 1, tzinfo=timezone.utc)
        me = datetime(cy + (cm == 12), (cm % 12) + 1, 1, tzinfo=timezone.utc)
        if ms > end: break
        months.append((ms, me))
        cm = (cm % 12) + 1
        if cm == 1: cy += 1
    rets, dds = [], []
    for ms, me in months:
        m_tr = [t for t in pool if ms <= to_utc(t["entry_ts"]) < me]
        if len(m_tr) < 10: continue
        r = production_replay(m_tr, cfg)
        if r is None: continue
        rets.append(r.total_return * 100)
        dds.append(r.max_drawdown * 100)
    n = len(rets)
    mu = sum(rets) / n
    std = (sum((x - mu) ** 2 for x in rets) / (n - 1)) ** 0.5 if n > 1 else 0
    # compound annual
    comp = 1.0
    for x in rets: comp *= (1 + x / 100)
    annual = (comp ** (12.0 / n) - 1) * 100 if n > 0 else 0
    worst_dd = min(dds) if dds else 0
    return {
        "n": n, "mean": mu, "annual": annual, "cv": std / abs(mu) * 100 if mu else 1e9,
        "pos": sum(1 for x in rets if x > 0), "neg": sum(1 for x in rets if x < 0),
        "max_loss": min(rets), "worst_month_dd": worst_dd,
        "r_adj": annual / abs(worst_dd) if worst_dd else 0,
    }


def walk_forward(pool, cfg, train_days=730, oos_days=90, step_days=30):
    pool = sorted(pool, key=lambda x: to_utc(x["entry_ts"]))
    start = to_utc(pool[0]["entry_ts"])
    end = to_utc(pool[-1]["exit_ts"])
    anns, dds = [], []
    cur = start
    while cur + timedelta(days=train_days + oos_days) <= end:
        os_s = cur + timedelta(days=train_days)
        os_e = os_s + timedelta(days=oos_days)
        oos_tr = [t for t in pool if os_s <= to_utc(t["entry_ts"]) < os_e]
        if len(oos_tr) >= 10:
            r = production_replay(oos_tr, cfg)
            if r is not None:
                anns.append(r.annualized(oos_days / 365.0) * 100)
                dds.append(r.max_drawdown * 100)
        cur += timedelta(days=step_days)
    if not anns:
        return None
    ma = sum(anns) / len(anns)
    md = sum(dds) / len(dds)
    return {
        "windows": len(anns), "mean_annual": ma, "mean_dd": md,
        "r_adj": ma / abs(md) if md else 0,
        "neg": sum(1 for a in anns if a < 0), "min": min(anns), "max": max(anns),
    }


def main():
    print(f"[load] {POOL.name}", flush=True)
    with POOL.open("rb") as f:
        pool = pickle.load(f)
    print(f"  pool: {len(pool):,} trade", flush=True)

    base = ProductionConfig.from_yaml(str(YAML))
    print(f"  base cfg: pyramid={base.pyramid_enabled} trig={base.pyramid_triggers} "
          f"sizes={base.pyramid_sizes} conf_min={base.conf_min}", flush=True)

    scenarios = [
        ("F  pyramid OFF (baseline)",
         lambda c: c.with_overrides(pyramid_enabled=False, pyramid_triggers=(), pyramid_sizes=())),
        ("CURRENT pyr [1.0,1.5]x[.5,.3]",
         lambda c: c),
        ("E  trigger ayrimi [2.0,3.0]",
         lambda c: c.with_overrides(pyramid_triggers=(2.0, 3.0))),
        ("E2 trigger ayrimi [2.5,3.5]",
         lambda c: c.with_overrides(pyramid_triggers=(2.5, 3.5))),
        ("C  size kucult [0.25,0.15]",
         lambda c: c.with_overrides(pyramid_sizes=(0.25, 0.15))),
        ("CE trig[2.0,3.0]+size[.25,.15]",
         lambda c: c.with_overrides(pyramid_triggers=(2.0, 3.0), pyramid_sizes=(0.25, 0.15))),
    ]

    for fee in (0.0, 8.0):
        print(f"\n{'='*92}", flush=True)
        print(f"FEE = {fee:+.0f} bps  {'(YAML default — zero fee)' if fee==0 else '(realistik worst-case taker)'}", flush=True)
        print(f"{'='*92}", flush=True)
        print(f"--- PER-MONTH (61 ay 2021-05 -> 2026-05) ---", flush=True)
        print(f"{'senaryo':<34}{'annual':>11}{'mean':>9}{'r-adj':>8}{'neg':>6}{'maxloss':>10}{'wmDD':>9}{'CV':>7}", flush=True)
        print("-" * 92, flush=True)
        pm_results = {}
        for name, fn in scenarios:
            cfg = fn(base).with_overrides(fee_bps_per_trade=fee)
            r = per_month(pool, cfg)
            pm_results[name] = r
            print(f"{name:<34}{r['annual']:>+10.1f}%{r['mean']:>+8.2f}%{r['r_adj']:>8.2f}"
                  f"{r['neg']:>6d}{r['max_loss']:>+9.2f}%{r['worst_month_dd']:>+8.1f}%{r['cv']:>6.0f}%", flush=True)

        print(f"\n--- WALK-FORWARD (2y train / 90d OOS / 30d step) ---", flush=True)
        print(f"{'senaryo':<34}{'mean_ann':>11}{'mean_dd':>10}{'r-adj':>8}{'neg':>6}{'wins':>7}", flush=True)
        print("-" * 92, flush=True)
        for name, fn in scenarios:
            cfg = fn(base).with_overrides(fee_bps_per_trade=fee)
            r = walk_forward(pool, cfg)
            if r is None:
                print(f"{name:<34}{'(no windows)':>20}", flush=True)
                continue
            print(f"{name:<34}{r['mean_annual']:>+10.1f}%{r['mean_dd']:>+9.1f}%{r['r_adj']:>8.2f}"
                  f"{r['neg']:>6d}{r['windows']:>7d}", flush=True)

        # delta vs CURRENT
        cur = pm_results["CURRENT pyr [1.0,1.5]x[.5,.3]"]
        f_base = pm_results["F  pyramid OFF (baseline)"]
        print(f"\n--- DELTA (per-month) vs CURRENT ---", flush=True)
        for name in pm_results:
            if name.startswith("CURRENT"): continue
            r = pm_results[name]
            print(f"  {name:<34} annual {r['annual']-cur['annual']:+8.1f}pp  "
                  f"r-adj {r['r_adj']-cur['r_adj']:+6.2f}  neg {r['neg']-cur['neg']:+d}  "
                  f"maxloss {r['max_loss']-cur['max_loss']:+.2f}pp", flush=True)


if __name__ == "__main__":
    main()
