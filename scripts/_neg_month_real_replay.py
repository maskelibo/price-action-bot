"""GERCEK production_replay ile per-ay executed trade dump.

lab.py'a eklenen `_executed_buffer` hook'u (object.__setattr__ ile bypass)
sayesinde gercek replay sirasi + DD breakerlar + cooldown + pyramid
mantiginin TAM aynisi ile executed trade listesini toplar.

Bu scriptin amaci: 7 neg ay'da hangi trade'ler GERCEKTEN tetiklendi,
sebep-sonuc zinciri (ilk kayipsa hangi side/sym/strat -> halt -> reopen)
"""
from __future__ import annotations

import io
import os
import pickle
import sys
from collections import Counter, defaultdict
from dataclasses import replace
from datetime import datetime, timezone, timedelta
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

NEG_MONTHS = ["2025-07", "2026-02", "2024-02", "2025-01", "2026-03", "2024-10"]


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
    print("=" * 110)
    print("REAL PRODUCTION REPLAY — per neg month executed trade dump (lab.py hook)")
    print("=" * 110)

    with POOL_15M.open("rb") as fh:
        pool_raw = pickle.load(fh)
    pool = [t for t in pool_raw if t.get("strategy") in TOP4 and t.get("symbol") in SYMS]
    pool.sort(key=lambda x: to_utc(x["entry_ts"]))
    print(f"\n[pool] {len(pool):,} trade")

    cfg = ProductionConfig.from_yaml(str(YAML_15M))
    cfg = cfg.with_overrides(max_concurrent=20, same_symbol_side_cooldown_days=0)
    cfg = replace(cfg, btc_halt_calendar=None)

    print(f"[cfg] daily_dd={cfg.daily_dd} weekly_dd={cfg.weekly_dd} monthly_dd={cfg.monthly_dd}")
    print(f"      monthly_long={cfg.monthly_dd_long} monthly_short={cfg.monthly_dd_short}")
    print(f"      halt_days: D={cfg.daily_halt_days} W={cfg.weekly_halt_days} M={cfg.monthly_halt_days}")
    print(f"      consec_n={cfg.consecutive_loss_n} consec_pause_days={cfg.consecutive_loss_pause_days}")
    print(f"      pyramid={cfg.pyramid_enabled} triggers={cfg.pyramid_triggers} sizes={cfg.pyramid_sizes}")
    print(f"      max_conc={cfg.max_concurrent} cooldown_days={cfg.same_symbol_side_cooldown_days}")

    overall_side_stats = defaultdict(list)
    overall_strat_stats = defaultdict(list)
    overall_sym_stats = defaultdict(list)

    for ym in NEG_MONTHS:
        start, end = month_bounds(ym)
        m_raw = [t for t in pool if start <= to_utc(t["entry_ts"]) < end]

        # Hook: bypass frozen dataclass via object.__setattr__
        buf = []
        object.__setattr__(cfg, "_executed_buffer", buf)

        r = production_replay(m_raw, cfg)
        if r is None:
            print(f"\n[{ym}] replay None (raw={len(m_raw)})")
            continue

        ret_pct = r.total_return * 100
        dd_pct = r.max_drawdown * 100

        print(f"\n{'='*110}")
        print(f"{ym} | ret={ret_pct:+.2f}% | DD={dd_pct:+.2f}% | trades={r.trades} | sum_R={r.sum_r:+.2f} | WR={r.win_rate*100:.1f}%")
        print(f"  raw pool n={len(m_raw)}")
        print(f"{'='*110}")

        # Forensic per-trade breakdown
        side_R, strat_R, sym_R = defaultdict(list), defaultdict(list), defaultdict(list)
        for e in buf:
            side_R[e["side"]].append(e["R_final"])
            strat_R[e["strategy"]].append(e["R_final"])
            sym_R[e["symbol"]].append(e["R_final"])

        print(f"  SIDE  : " + " | ".join([f"{k}: n={len(v)} sum_R={sum(v):+.2f}" for k,v in sorted(side_R.items())]))
        print(f"  STRAT : " + " | ".join([f"{k}: n={len(v)} sum_R={sum(v):+.2f}" for k,v in sorted(strat_R.items(), key=lambda x: sum(x[1]))]))
        print(f"  SYM   : " + " | ".join([f"{k}: n={len(v)} sum_R={sum(v):+.2f}" for k,v in sorted(sym_R.items(), key=lambda x: sum(x[1]))]))

        # Per-trade chronological
        print(f"\n  ALL EXECUTED trades:")
        sorted_buf = sorted(buf, key=lambda x: to_utc(x["entry_ts"]) if x.get("entry_ts") else to_utc(x["exit_ts"]))
        for e in sorted_buf:
            ets_raw = e.get("entry_ts")
            xts_raw = e["exit_ts"]
            ets = to_utc(ets_raw).strftime("%m-%d %H:%M") if ets_raw else "??"
            xts = to_utc(xts_raw).strftime("%m-%d %H:%M")
            pyr_amp = ""
            if e.get("peak_R") and e["peak_R"] >= 1.0:
                pyr_amp = f"  PYRAMID peak={e['peak_R']:+.2f}"
            print(f"    {ets} -> {xts}  {e['symbol']:<10} {e['side']:<5} {e['strategy']:<25} R_raw={e['R_raw']:+.2f} R_final={e['R_final']:+.2f} pnl=${e['pnl']:+7.0f} eq=${e['equity']:,.0f}{pyr_amp}")

        # Accumulate cross-month stats
        for s, rs in side_R.items():
            overall_side_stats[s].extend(rs)
        for s, rs in strat_R.items():
            overall_strat_stats[s].extend(rs)
        for s, rs in sym_R.items():
            overall_sym_stats[s].extend(rs)

    # Cross-month aggregate
    print(f"\n{'='*110}")
    print(f"AGGREGATE (6 neg months combined)")
    print(f"{'='*110}")

    def fmt_stat(stats):
        out = []
        for k, v in sorted(stats.items(), key=lambda x: sum(x[1])):
            losers = sum(1 for r in v if r < 0)
            out.append(f"{k}: n={len(v)} sum_R={sum(v):+.2f} losers={losers}/{len(v)} ({losers/len(v)*100:.0f}%) mean_R={sum(v)/len(v):+.3f}")
        return out

    print(f"\nSIDE aggregate:")
    for line in fmt_stat(overall_side_stats):
        print(f"  {line}")
    print(f"\nSTRATEGY aggregate:")
    for line in fmt_stat(overall_strat_stats):
        print(f"  {line}")
    print(f"\nSYMBOL aggregate:")
    for line in fmt_stat(overall_sym_stats):
        print(f"  {line}")


if __name__ == "__main__":
    main()
