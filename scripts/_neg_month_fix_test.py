"""Fix Test — 4 mikro-fix variant per-ay replay ile dene.

Baseline: TOP4 (vsa+brooks_fb+anchored_vwap+engulfing_continuation) + pyramid + halt OFF
  → yıllık +%1076, 7 neg ay

Variants:
  F1: TOP3 (engulfing_continuation DROP) — en zayif halka cikar
  F2: same_symbol_side_cooldown 0 → 0.011 (~16 dakika; cluster yumusatma)
  F3: pyramid_triggers (1.0, 2.0) → (1.5, 2.5) — daha gec trigger, false peak cilirgini azalt
  F4: F1 + drop ADA/USDT (en kotu sym: 13/16 loser, mean_R -0.71)
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
TOP3 = {"vsa_climax_test", "brooks_failed_breakout",
        "anchored_vwap_reversal"}
SYMS_ALL = {"BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT", "ADA/USDT",
            "AVAX/USDT", "LINK/USDT", "DOT/USDT", "DOGE/USDT", "XRP/USDT"}
SYMS_NO_ADA = SYMS_ALL - {"ADA/USDT"}
SYMS_NO_ADA_DOGE_SOL = SYMS_ALL - {"ADA/USDT", "DOGE/USDT", "SOL/USDT"}


def to_utc(ts):
    if hasattr(ts, "tz_localize"):
        if ts.tzinfo is None:
            return ts.tz_localize("UTC")
        return ts.tz_convert("UTC")
    if ts.tzinfo is None:
        return ts.replace(tzinfo=timezone.utc)
    return ts.astimezone(timezone.utc)


def month_bounds_iter(start_dt, end_dt):
    cy, cm = start_dt.year, start_dt.month
    while True:
        ms = datetime(cy, cm, 1, tzinfo=timezone.utc)
        if cm == 12:
            me = datetime(cy + 1, 1, 1, tzinfo=timezone.utc)
        else:
            me = datetime(cy, cm + 1, 1, tzinfo=timezone.utc)
        if ms > end_dt:
            break
        yield f"{cy:04d}-{cm:02d}", ms, me
        cm += 1
        if cm > 12:
            cm = 1
            cy += 1


def run_variant(label, pool_full, strats, syms, cfg_override=None):
    pool = [t for t in pool_full if t.get("strategy") in strats and t.get("symbol") in syms]
    pool.sort(key=lambda x: to_utc(x["entry_ts"]))
    if not pool:
        return None

    cfg = ProductionConfig.from_yaml(str(YAML_15M))
    cfg = cfg.with_overrides(max_concurrent=20, same_symbol_side_cooldown_days=0)
    cfg = replace(cfg, btc_halt_calendar=None)
    if cfg_override:
        cfg = replace(cfg, **cfg_override)

    start = to_utc(pool[0]["entry_ts"])
    end = to_utc(pool[-1]["entry_ts"])
    rows = []
    for ym, ms, me in month_bounds_iter(start, end):
        m_trades = [t for t in pool if ms <= to_utc(t["entry_ts"]) < me]
        if len(m_trades) < 10:
            rows.append({"ym": ym, "ret": 0.0, "dd": 0.0, "n": 0, "n_raw": len(m_trades)})
            continue
        r = production_replay(m_trades, cfg)
        if r is None:
            rows.append({"ym": ym, "ret": 0.0, "dd": 0.0, "n": 0, "n_raw": len(m_trades)})
            continue
        rows.append({
            "ym": ym, "ret": r.total_return * 100, "dd": r.max_drawdown * 100,
            "n": r.trades, "n_raw": len(m_trades)
        })

    rets = [r["ret"] for r in rows]
    n_months = len(rets)
    n_pos = sum(1 for x in rets if x > 0)
    n_neg = sum(1 for x in rets if x < 0)
    n_zero = sum(1 for x in rets if x == 0)
    n_ge20 = sum(1 for x in rets if x >= 20)
    n_ge25 = sum(1 for x in rets if x >= 25)
    mean_r = mean(rets) if rets else 0
    # compound monthly returns (capped at -100%)
    eq = 1.0
    for r in rets:
        eq *= max(0.01, (1 + r/100))
    annualized = (eq ** (12.0 / n_months) - 1.0) * 100 if n_months > 0 else 0

    return {
        "label": label, "rows": rows,
        "n_months": n_months, "mean_monthly": mean_r,
        "n_pos": n_pos, "n_neg": n_neg, "n_zero": n_zero,
        "n_ge20": n_ge20, "n_ge25": n_ge25,
        "annual_compound": annualized,
        "neg_months": sorted([r for r in rows if r["ret"] < 0], key=lambda x: x["ret"]),
    }


def main():
    print("=" * 110)
    print("FIX VARIANT TEST — neg month reduction sprint")
    print("=" * 110)

    with POOL_15M.open("rb") as fh:
        pool_full = pickle.load(fh)
    print(f"\n[pool] full = {len(pool_full):,} trade")

    variants = [
        ("BASELINE TOP4 + pyramid", TOP4, SYMS_ALL, None),
        ("F1: TOP3 (drop engulfing)", TOP3, SYMS_ALL, None),
        ("F2: cooldown 16dk", TOP4, SYMS_ALL, {"same_symbol_side_cooldown_days": 0.011}),
        ("F3: pyramid trig (1.5,2.5)", TOP4, SYMS_ALL,
         {"pyramid_triggers": (1.5, 2.5), "pyramid_sizes": (0.5, 0.3)}),
        ("F4: F1 + drop ADA", TOP3, SYMS_NO_ADA, None),
        ("F5: F1 + drop ADA+DOGE+SOL", TOP3, SYMS_NO_ADA_DOGE_SOL, None),
        ("F6: TOP3 + pyramid (1.5,2.5)", TOP3, SYMS_ALL,
         {"pyramid_triggers": (1.5, 2.5), "pyramid_sizes": (0.5, 0.3)}),
        ("F7: F1 + cooldown 30dk", TOP3, SYMS_ALL, {"same_symbol_side_cooldown_days": 0.021}),
    ]

    results = []
    for label, strats, syms, override in variants:
        print(f"\n[run] {label}")
        res = run_variant(label, pool_full, strats, syms, override)
        if res is None:
            print(f"  EMPTY")
            continue
        results.append(res)
        print(f"  annual_compound={res['annual_compound']:+.1f}% "
              f"mean_monthly={res['mean_monthly']:+.2f}% "
              f"pos={res['n_pos']} neg={res['n_neg']} zero={res['n_zero']} "
              f"ge20={res['n_ge20']} ge25={res['n_ge25']}")
        if res['neg_months']:
            print(f"  NEG MONTHS ({len(res['neg_months'])}):")
            for nm in res['neg_months']:
                print(f"    {nm['ym']}: {nm['ret']:+.2f}% (n={nm['n']}, raw={nm['n_raw']})")

    # Summary table
    print(f"\n{'='*110}")
    print(f"SUMMARY")
    print(f"{'='*110}")
    print(f"{'label':<35} {'annual':>10} {'mean_mo':>9} {'pos':>5} {'neg':>5} {'zero':>5} {'ge20':>5} {'ge25':>5}")
    for r in results:
        print(f"{r['label']:<35} {r['annual_compound']:+9.1f}% {r['mean_monthly']:+8.2f}% "
              f"{r['n_pos']:>5} {r['n_neg']:>5} {r['n_zero']:>5} {r['n_ge20']:>5} {r['n_ge25']:>5}")


if __name__ == "__main__":
    main()
