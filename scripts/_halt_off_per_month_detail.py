"""Halt OFF 15m R4 per-ay detay — sec49 sıfır-ayları + halt OFF kıyas.

Halt OFF + pyramid ON config'inde 61 ay detaylı:
  - Hangi aylar negatif (n=7) — rejim/sebep tanımla
  - Hangi 2 ay halt OFF'da bile sıfır (trade<10) — micro-rejim mi?
  - MR pool için en faydalı aylar (mean low, neg yok ama de patlama yok)
  - Pyramid katkısı bull aylarda mı, bear aylarda da mı?
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

POOL_15M = ROOT / "data" / "sec31_15m_pool.pkl"
YAML_15M = ROOT / "configs" / "risk_phoenix_scalp_15m_pyramid_r3.yaml"
CSV_OUT = ROOT / "reports" / "engineering" / "2026-05-17_halt_off_per_month_detail.csv"
MD_OUT = ROOT / "reports" / "engineering" / "2026-05-17_halt_off_per_month_detail.md"

TOP4 = {"vsa_climax_test", "brooks_failed_breakout",
        "anchored_vwap_reversal", "engulfing_continuation"}
SYMS = {"BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT", "ADA/USDT",
        "AVAX/USDT", "LINK/USDT", "DOT/USDT", "DOGE/USDT", "XRP/USDT"}


def to_utc(ts):
    if hasattr(ts, "tz_localize"):
        if ts.tzinfo is None:
            return ts.tz_localize("UTC")
        return ts.tz_convert("UTC")
    if ts.tzinfo is None:
        return ts.replace(tzinfo=timezone.utc)
    return ts.astimezone(timezone.utc)


def main():
    print("=" * 78)
    print("Halt OFF 15m R4 — 61-ay detay")
    print("=" * 78)

    print(f"\n[LOAD] {POOL_15M.name}")
    with POOL_15M.open("rb") as fh:
        pool_raw = pickle.load(fh)
    pool = [t for t in pool_raw
            if t.get("strategy") in TOP4 and t.get("symbol") in SYMS]
    print(f"  pool: {len(pool):,} trade")

    cfg = ProductionConfig.from_yaml(str(YAML_15M))
    cfg = cfg.with_overrides(max_concurrent=20, same_symbol_side_cooldown_days=0)
    cfg = replace(cfg, btc_halt_calendar=None)

    pool.sort(key=lambda x: x["entry_ts"])
    start = to_utc(pool[0]["entry_ts"])
    end = to_utc(pool[-1]["entry_ts"])

    print(f"\n[STEP] Per-ay replay (halt OFF + pyramid ON)")
    rows = []
    cy, cm = start.year, start.month
    while True:
        ms = datetime(cy, cm, 1, tzinfo=timezone.utc)
        if cm == 12:
            me = datetime(cy + 1, 1, 1, tzinfo=timezone.utc)
        else:
            me = datetime(cy, cm + 1, 1, tzinfo=timezone.utc)
        if ms > end:
            break

        m_trades = [t for t in pool if ms <= to_utc(t["entry_ts"]) < me]
        n_raw = len(m_trades)
        if n_raw < 10:
            rows.append({"yyyy_mm": f"{cy:04d}-{cm:02d}", "n_raw": n_raw,
                         "ret_pct": 0.0, "dd_pct": 0.0, "trades": 0, "note": "skipped <10"})
        else:
            r = production_replay(m_trades, cfg)
            if r is None:
                rows.append({"yyyy_mm": f"{cy:04d}-{cm:02d}", "n_raw": n_raw,
                             "ret_pct": 0.0, "dd_pct": 0.0, "trades": 0, "note": "replay None"})
            else:
                rows.append({
                    "yyyy_mm": f"{cy:04d}-{cm:02d}",
                    "n_raw": n_raw,
                    "ret_pct": round(r.total_return * 100, 3),
                    "dd_pct": round(r.max_drawdown * 100, 3),
                    "trades": r.trades,
                    "note": "",
                })

        cm += 1
        if cm > 12:
            cm = 1
            cy += 1

    # CSV
    CSV_OUT.parent.mkdir(parents=True, exist_ok=True)
    with CSV_OUT.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["yyyy_mm", "n_raw", "ret_pct", "dd_pct", "trades", "note"])
        w.writeheader()
        w.writerows(rows)
    print(f"  CSV → {CSV_OUT}")

    # Analysis
    rets = [r["ret_pct"] for r in rows]
    n = len(rets)
    mean_r = sum(rets) / n
    pos = sum(1 for x in rets if x > 0)
    neg = sum(1 for x in rets if x < 0)
    zero = sum(1 for x in rets if x == 0)
    ge20 = sum(1 for x in rets if x >= 20)
    ge15 = sum(1 for x in rets if x >= 15)
    ge10 = sum(1 for x in rets if x >= 10)
    ge5 = sum(1 for x in rets if x >= 5)

    print(f"\n[SUMMARY] n={n}, mean={mean_r:+.2f}%, pos={pos}, neg={neg}, zero={zero}")
    print(f"          ge20={ge20} ge15={ge15} ge10={ge10} ge5={ge5}")

    neg_rows = sorted([r for r in rows if r["ret_pct"] < 0], key=lambda x: x["ret_pct"])
    print(f"\n[NEGATIVE MONTHS] (n={len(neg_rows)})")
    for r in neg_rows:
        print(f"  {r['yyyy_mm']}: {r['ret_pct']:+.2f}% (trades={r['trades']}, raw={r['n_raw']})")

    zero_rows = [r for r in rows if r["ret_pct"] == 0.0 and r["n_raw"] >= 10]
    print(f"\n[ZERO MONTHS (despite raw>=10)] (n={len(zero_rows)})")
    for r in zero_rows:
        print(f"  {r['yyyy_mm']}: trades={r['trades']}, raw={r['n_raw']} note={r['note']}")

    sub_15_rows = sorted([r for r in rows if 0 <= r["ret_pct"] < 15], key=lambda x: x["ret_pct"])
    print(f"\n[SUB-15 MONTHS] (n={len(sub_15_rows)}, candidates for MR pool uplift)")
    for r in sub_15_rows[:15]:
        print(f"  {r['yyyy_mm']}: {r['ret_pct']:+.2f}% (trades={r['trades']})")
    if len(sub_15_rows) > 15:
        print(f"  ... +{len(sub_15_rows)-15} more")


if __name__ == "__main__":
    main()
