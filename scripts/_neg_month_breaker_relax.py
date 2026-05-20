"""Breaker relaxation test — neg ay'lardaki halt'ların erken kesimini gevşetince
ne olur? Mevcut: daily_dd 3%, weekly_dd 8%, monthly_long 10%, monthly_short 4%.

Hipotez: monthly_short 4% (KÜÇÜK) → bear ralilerinde short kayıpları kısa
sürede halt yaratıyor → reopen short bias kalır.

Test variants:
  R0 baseline
  R1: monthly_short 4% -> 8% (long ile eşit)
  R2: monthly_short -> 8% + daily_dd 3% -> 5%
  R3: monthly_short -> 12% (gevşek)
  R4: daily_halt_days 1 -> 0 (intraday reset)
  R5: weekly_dd 8% -> 12%
"""
from __future__ import annotations

import io
import os
import pickle
import sys
from collections import defaultdict
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean

if __name__ == "__main__":
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
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

from price_action.backtest.lab import ProductionConfig, production_replay

POOL_15M = ROOT / "data" / "sec31_15m_pool.pkl"
YAML_15M = ROOT / "configs" / "risk_phoenix_scalp_15m_pyramid_r3.yaml"
TOP4 = {"vsa_climax_test", "brooks_failed_breakout",
        "anchored_vwap_reversal", "engulfing_continuation"}
SYMS = {"BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT", "ADA/USDT",
        "AVAX/USDT", "LINK/USDT", "DOT/USDT", "DOGE/USDT", "XRP/USDT"}


def to_utc(ts):
    if hasattr(ts, "tz_localize"):
        if ts.tzinfo is None:
            return ts.tz_localize("UTC")
        return ts.tz_convert("UTC")
    return ts


def month_bounds_iter(start_dt, end_dt):
    cy, cm = start_dt.year, start_dt.month
    while True:
        ms = datetime(cy, cm, 1, tzinfo=timezone.utc)
        me = datetime(cy + (1 if cm == 12 else 0), 1 if cm == 12 else cm + 1, 1, tzinfo=timezone.utc)
        if ms > end_dt:
            break
        yield f"{cy:04d}-{cm:02d}", ms, me
        cm = 1 if cm == 12 else cm + 1
        cy = cy + 1 if cm == 1 else cy


def run_variant(label, pool, cfg_override=None):
    cfg = ProductionConfig.from_yaml(str(YAML_15M))
    cfg = cfg.with_overrides(max_concurrent=20, same_symbol_side_cooldown_days=0)
    cfg = replace(cfg, btc_halt_calendar=None)
    if cfg_override:
        cfg = replace(cfg, **cfg_override)

    start = to_utc(pool[0]["entry_ts"])
    end = to_utc(pool[-1]["entry_ts"])
    rows = []
    for ym, ms, me in month_bounds_iter(start, end):
        m_t = [t for t in pool if ms <= to_utc(t["entry_ts"]) < me]
        if len(m_t) < 10:
            rows.append({"ym": ym, "ret": 0.0, "n": 0})
            continue
        r = production_replay(m_t, cfg)
        rows.append({"ym": ym, "ret": r.total_return * 100 if r else 0, "n": r.trades if r else 0})

    rets = [r["ret"] for r in rows]
    n = len(rets)
    n_pos = sum(1 for x in rets if x > 0)
    n_neg = sum(1 for x in rets if x < 0)
    n_zero = sum(1 for x in rets if x == 0)
    n_ge20 = sum(1 for x in rets if x >= 20)
    n_ge25 = sum(1 for x in rets if x >= 25)
    eq = 1.0
    for r in rets:
        eq *= max(0.01, 1 + r/100)
    annualized = (eq ** (12.0 / n) - 1.0) * 100 if n > 0 else 0
    return {
        "label": label, "rows": rows, "annual": annualized,
        "mean": mean(rets), "n_pos": n_pos, "n_neg": n_neg, "n_zero": n_zero,
        "ge20": n_ge20, "ge25": n_ge25,
        "neg_months": sorted([r for r in rows if r["ret"] < 0], key=lambda x: x["ret"]),
    }


def main():
    print("=" * 110)
    print("BREAKER RELAXATION SWEEP — neg ay reduction via halt tuning")
    print("=" * 110)

    with POOL_15M.open("rb") as fh:
        pool_raw = pickle.load(fh)
    pool = [t for t in pool_raw if t.get("strategy") in TOP4 and t.get("symbol") in SYMS]
    pool.sort(key=lambda x: to_utc(x["entry_ts"]))
    print(f"\n[pool] {len(pool):,} trade")

    variants = [
        ("R0 baseline", None),
        ("R1 monthly_short 4 -> 8", {"monthly_dd_short": 0.08}),
        ("R2 m_short 8 + daily 5", {"monthly_dd_short": 0.08, "daily_dd": 0.05}),
        ("R3 m_short -> 12", {"monthly_dd_short": 0.12}),
        ("R4 daily_halt_days 1->0", {"daily_halt_days": 0}),
        ("R5 weekly_dd 8 -> 12", {"weekly_dd": 0.12}),
        ("R6 m_short 8 + halt_days D=0", {"monthly_dd_short": 0.08, "daily_halt_days": 0}),
        ("R7 m_short 8 + m_long 15", {"monthly_dd_short": 0.08, "monthly_dd_long": 0.15}),
    ]

    results = []
    for label, ov in variants:
        print(f"\n[run] {label}")
        r = run_variant(label, pool, ov)
        results.append(r)
        print(f"  annual={r['annual']:+.1f}% mean_mo={r['mean']:+.2f}% pos={r['n_pos']} neg={r['n_neg']} zero={r['n_zero']} ge20={r['ge20']} ge25={r['ge25']}")
        for nm in r['neg_months']:
            print(f"    NEG {nm['ym']}: {nm['ret']:+.2f}% (n={nm['n']})")

    print(f"\n{'='*110}")
    print(f"SUMMARY")
    print(f"{'='*110}")
    print(f"{'label':<32} {'annual':>10} {'mean_mo':>9} {'pos':>5} {'neg':>5} {'zero':>5} {'ge20':>5} {'ge25':>5}")
    for r in results:
        print(f"{r['label']:<32} {r['annual']:+9.1f}% {r['mean']:+8.2f}% {r['n_pos']:>5} {r['n_neg']:>5} {r['n_zero']:>5} {r['ge20']:>5} {r['ge25']:>5}")


if __name__ == "__main__":
    main()
