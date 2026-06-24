"""SEC50-STRK — EMA200_streak sweep (diagnostic'e göre baskın trigger).

Diagnostic (2026-05-17): halt 732/1843 gün, STRK trigger 671 gün baskın.
Mevcut slim sweep STRK=10 sabit tutuyor — yetersiz olabilir.

Bu script STRK boyutunu sweeple:
  STRK grid: 10 (1d default), 20, 30, 50, 90, OFF (STRK kontrolünü pasifize)
  ATR sabit 6.0 + DD sabit -25.0 (1d default)
  + en iyi ATR×DD slim sweep'den alınabilir (mevcut sweep tamamlanırsa)

Tahmini süre: ~5-7 dk (6 senaryo + halt OFF baseline).
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

import pandas as pd

from price_action.backtest.lab import ProductionConfig, production_replay
from price_action.backtest.regime import compute_btc_capitulation_halt

CSV_OUT = ROOT / "reports" / "engineering" / "2026-05-17_halt_15m_strk_sweep.csv"
POOL_15M = ROOT / "data" / "sec31_15m_pool.pkl"
YAML_15M = ROOT / "configs" / "risk_phoenix_scalp_15m_pyramid_r3.yaml"

TOP4_STRATEGIES = {
    "vsa_climax_test",
    "brooks_failed_breakout",
    "anchored_vwap_reversal",
    "engulfing_continuation",
}
SYMBOLS_10 = {
    "BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT", "ADA/USDT",
    "AVAX/USDT", "LINK/USDT", "DOT/USDT", "DOGE/USDT", "XRP/USDT",
}

# STRK sweep — gevşeterek halt'i azalt
STRK_GRID = [10, 20, 30, 50, 90]
ATR_FIXED = 6.0
DD_FIXED = -25.0


def to_utc(ts):
    if hasattr(ts, "tz_localize"):
        if ts.tzinfo is None:
            return ts.tz_localize("UTC")
        return ts.tz_convert("UTC")
    if ts.tzinfo is None:
        return ts.replace(tzinfo=timezone.utc)
    return ts.astimezone(timezone.utc)


def per_month_replay(pool, cfg, halt_calendar, label):
    cfg_local = replace(cfg, btc_halt_calendar=halt_calendar)
    pool.sort(key=lambda x: x["entry_ts"])
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

    results = []
    for yr, mo, ms, me in months:
        m_trades = [t for t in pool if ms <= to_utc(t["entry_ts"]) < me]
        if len(m_trades) < 10:
            continue
        r = production_replay(m_trades, cfg_local)
        if r is None:
            continue
        ret_pct = r.total_return * 100
        dd_pct = r.max_drawdown * 100
        results.append((yr, mo, len(m_trades), ret_pct, dd_pct))

    rets = [r[3] for r in results]
    n = len(rets)
    if n == 0:
        return results, {"label": label, "n_months": 0}

    mean_ret = sum(rets) / n
    std = (sum((x - mean_ret) ** 2 for x in rets) / (n - 1)) ** 0.5 if n > 1 else 0.0
    cv_pct = (std / abs(mean_ret) * 100) if mean_ret != 0 else float("inf")
    pos = sum(1 for x in rets if x > 0)
    neg = sum(1 for x in rets if x < 0)
    zero = sum(1 for x in rets if x == 0)
    ge20 = sum(1 for x in rets if x >= 20.0)
    ge15 = sum(1 for x in rets if x >= 15.0)

    return results, {
        "label": label,
        "n_months": n,
        "mean_pct": round(mean_ret, 3),
        "std_pct": round(std, 3),
        "cv_pct": round(cv_pct, 1),
        "min_pct": round(min(rets), 3),
        "max_pct": round(max(rets), 3),
        "pos": pos, "neg": neg, "zero": zero, "ge20": ge20, "ge15": ge15,
    }


def main():
    print("=" * 78)
    print("SEC50-STRK — EMA200_streak sweep (15m R4)")
    print("=" * 78)

    print("\n[LOAD] 15m pool + cfg")
    with POOL_15M.open("rb") as fh:
        pool_raw = pickle.load(fh)
    pool = [
        t for t in pool_raw
        if t.get("strategy") in TOP4_STRATEGIES
        and t.get("symbol") in SYMBOLS_10
    ]
    print(f"  pool: {len(pool):,} trade")

    cfg = ProductionConfig.from_yaml(str(YAML_15M))
    cfg = cfg.with_overrides(max_concurrent=20, same_symbol_side_cooldown_days=0)

    sweep_results = []
    print("\n[STEP 1] STRK sweep (ATR=6, DD=-25 sabit)")

    for strk in STRK_GRID:
        cal = compute_btc_capitulation_halt(ATR_FIXED, strk, DD_FIXED)
        hd = sum(1 for v in cal.values() if v)
        res, summ = per_month_replay(pool, cfg, cal, f"STRK={strk}")
        is_def = "(DEF)" if strk == 10 else ""
        print(f"  STRK={strk:>3} {is_def} → halt={hd} mean={summ['mean_pct']:+.2f}% "
              f"cv={summ['cv_pct']:.0f}% neg={summ['neg']} zero={summ['zero']} ge20={summ['ge20']}")
        sweep_results.append({"strk": strk, "halt_days": hd, **summ})

    # halt OFF
    print(f"\n  HALT OFF baseline")
    res_off, sum_off = per_month_replay(pool, cfg, None, "halt_OFF")
    print(f"  STRK={None} (OFF) → halt=0 mean={sum_off['mean_pct']:+.2f}% "
          f"cv={sum_off['cv_pct']:.0f}% neg={sum_off['neg']} zero={sum_off['zero']} ge20={sum_off['ge20']}")
    sweep_results.append({"strk": "OFF", "halt_days": 0, **sum_off})

    # CSV out
    print(f"\n[WRITE] {CSV_OUT}")
    CSV_OUT.parent.mkdir(parents=True, exist_ok=True)
    keys = ["strk", "halt_days", "label", "n_months", "mean_pct", "std_pct",
            "cv_pct", "min_pct", "max_pct", "pos", "neg", "zero", "ge20", "ge15"]
    with CSV_OUT.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=keys)
        w.writeheader()
        for row in sweep_results:
            w.writerow({k: row.get(k, "") for k in keys})

    # Best param
    print("\n[STEP 2] Best param")

    def score(r):
        if r["n_months"] == 0:
            return 1e9
        return (r["zero"] + r["neg"]) * 10 - r["mean_pct"] * 0.5

    sorted_sw = sorted(sweep_results, key=score)
    print(f"\n  Top-3 (composite score):")
    print(f"  {'STRK':>5} {'halt':>5} {'mean%':>8} {'cv%':>5} {'neg':>3} {'zero':>4} {'ge20':>4}")
    for r in sorted_sw[:3]:
        print(f"  {str(r['strk']):>5} {r['halt_days']:>5} {r['mean_pct']:>+8.2f} "
              f"{r['cv_pct']:>5.0f} {r['neg']:>3} {r['zero']:>4} {r['ge20']:>4}")

    print("\nDONE.")


if __name__ == "__main__":
    main()
