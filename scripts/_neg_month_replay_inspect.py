"""Replay-level inspection — Neg aylarda hangi trade'ler gerçekten alındı (post-filter)?
Raw pool sum_R pozitif (+1252 / +1656 / +1486...) AMA replay -%7'lere düşüyor →
Cooldown + max_concurrent + pyramid trade-selection bias'ı içe atıyor.

Bu script:
  - cfg ile replay yapar
  - replay'de gerçek tetiklenmiş trade'leri toplar (closed_trades)
  - 7 neg ay × per-trade dump
  - side / strategy / sym / R distribution → mikro-fix önerisi temeli
"""
from __future__ import annotations

import io
import os
import pickle
import sys
from collections import Counter, defaultdict
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean, stdev

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

NEG_MONTHS = ["2025-07", "2026-02", "2024-02", "2025-01", "2023-05", "2026-03", "2024-10"]


def to_utc(ts):
    if hasattr(ts, "tz_localize"):
        if ts.tzinfo is None:
            return ts.tz_localize("UTC")
        return ts.tz_convert("UTC")
    if ts.tzinfo is None:
        return ts.replace(tzinfo=timezone.utc)
    return ts.astimezone(timezone.utc)


def month_bounds(yyyy_mm):
    y, m = map(int, yyyy_mm.split("-"))
    start = datetime(y, m, 1, tzinfo=timezone.utc)
    if m == 12:
        end = datetime(y + 1, 1, 1, tzinfo=timezone.utc)
    else:
        end = datetime(y, m + 1, 1, tzinfo=timezone.utc)
    return start, end


def main():
    print("=" * 100)
    print("NEG MONTH REPLAY INSPECTION — per-trade post-filter dump")
    print("=" * 100)

    with POOL_15M.open("rb") as fh:
        pool_raw = pickle.load(fh)
    pool = [t for t in pool_raw
            if t.get("strategy") in TOP4 and t.get("symbol") in SYMS]
    print(f"\n[pool] {len(pool):,} trade (TOP4 × 10sym)")

    cfg = ProductionConfig.from_yaml(str(YAML_15M))
    cfg = cfg.with_overrides(max_concurrent=20, same_symbol_side_cooldown_days=0)
    cfg = replace(cfg, btc_halt_calendar=None)

    pool.sort(key=lambda x: to_utc(x["entry_ts"]))

    for ym in NEG_MONTHS:
        start, end = month_bounds(ym)
        m_raw = [t for t in pool if start <= to_utc(t["entry_ts"]) < end]
        if len(m_raw) < 5:
            print(f"\n[{ym}] raw pool too small (n={len(m_raw)})")
            continue
        r = production_replay(m_raw, cfg)
        if r is None or not hasattr(r, "executed_trades"):
            print(f"\n[{ym}] replay returned no executed_trades attr — fallback")
            attrs = [a for a in dir(r) if not a.startswith("_")] if r else []
            print(f"   r attrs: {attrs[:20]}")
            continue
        executed = r.executed_trades
        print(f"\n=== {ym} | ret={r.total_return*100:+.2f}% | dd={r.max_drawdown*100:+.2f}% | executed={len(executed)} ===")
        print(f"  raw_pool n={len(m_raw)} sum_R={sum(t['R'] for t in m_raw):+.2f}")
        # executed summary
        ex_sum = sum(t.realized_R for t in executed) if executed else 0
        print(f"  executed sum_R={ex_sum:+.2f}, mean_R={(ex_sum/len(executed) if executed else 0):+.3f}")

        # per side
        side_R = defaultdict(list)
        strat_R = defaultdict(list)
        sym_R = defaultdict(list)
        for t in executed:
            side_R[t.side].append(t.realized_R)
            strat_R[t.strategy].append(t.realized_R)
            sym_R[t.symbol].append(t.realized_R)
        print(f"  by SIDE  : {[(s, len(v), round(sum(v),2)) for s,v in sorted(side_R.items())]}")
        print(f"  by STRAT : {[(s, len(v), round(sum(v),2)) for s,v in sorted(strat_R.items(), key=lambda x: sum(x[1]))]}")
        print(f"  by SYM   : {[(s, len(v), round(sum(v),2)) for s,v in sorted(sym_R.items(), key=lambda x: sum(x[1]))]}")

        # per trade
        print(f"  --- trades ---")
        for t in executed:
            ets = to_utc(t.entry_ts).strftime("%m-%d %H:%M")
            xts = to_utc(t.exit_ts).strftime("%m-%d %H:%M") if t.exit_ts else "OPEN"
            print(f"    {ets} → {xts}  {t.symbol:<10} {t.side:<5} {t.strategy:<24} R={t.realized_R:+.2f} pyramids={getattr(t, 'pyramid_count', 0)}")


if __name__ == "__main__":
    main()
