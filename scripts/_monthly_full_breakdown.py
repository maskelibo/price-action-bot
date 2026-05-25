"""15m R4 v3.1 (canonical) — Aylık full breakdown.

User talebi: başlangıçtan en sona kadar, kaç işlem, aylık özet DD, WR, ROI,
giriş sermayesi, çıkış sermayesi.

Config: risk_phoenix_scalp_15m_pyramid_r3.yaml (Pyramid + Halt OFF + cooldown 15dk YAML)
Pool: data/sec31_15m_pool.pkl (5y × 10 sym × TOP-4)
Span: 2021-05 → 2026-05 (61 ay)

Compounded simulation: aylık equity geçmişten devralır (starting $10,000).
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
CSV_OUT = ROOT / "reports" / "engineering" / "2026-05-17_monthly_full_breakdown.csv"
MD_OUT = ROOT / "reports" / "engineering" / "2026-05-17_monthly_full_breakdown.md"

TOP4 = {"vsa_climax_test", "brooks_failed_breakout",
        "anchored_vwap_reversal", "engulfing_continuation"}
SYMS = {"BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT", "ADA/USDT",
        "AVAX/USDT", "LINK/USDT", "DOT/USDT", "DOGE/USDT", "XRP/USDT"}

INITIAL_EQUITY = 10000.0


def to_utc(ts):
    if hasattr(ts, "tz_localize"):
        if ts.tzinfo is None:
            return ts.tz_localize("UTC")
        return ts.tz_convert("UTC")
    if ts.tzinfo is None:
        return ts.replace(tzinfo=timezone.utc)
    return ts.astimezone(timezone.utc)


def main():
    print(f"[LOAD] {POOL_15M.name}")
    with POOL_15M.open("rb") as fh:
        pool_raw = pickle.load(fh)
    pool = [t for t in pool_raw if t.get("strategy") in TOP4 and t.get("symbol") in SYMS]
    print(f"  pool: {len(pool):,} trade")

    cfg = ProductionConfig.from_yaml(str(YAML_15M))
    cfg = cfg.with_overrides(max_concurrent=20, same_symbol_side_cooldown_days=0.010)
    cfg = replace(cfg, btc_halt_calendar=None)  # halt OFF
    print(f"[cfg] {YAML_15M.name} (pyramid_triggers={cfg.pyramid_triggers}, halt=None)")

    pool.sort(key=lambda x: x["entry_ts"])
    start = to_utc(pool[0]["entry_ts"])
    end = to_utc(pool[-1]["entry_ts"])

    # Build 61-ay calendar
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

    print(f"\n[STEP] Per-month replay (compounded, starting ${INITIAL_EQUITY:,.0f})")
    rows = []
    equity = INITIAL_EQUITY
    cum_trades = 0
    cum_wins = 0

    for yr, mo, ms, me in months:
        m_trades = [t for t in pool if ms <= to_utc(t["entry_ts"]) < me]
        n_raw = len(m_trades)
        start_equity = equity

        if n_raw < 10:
            # Skip - keep equity unchanged
            row = {
                "yyyy_mm": f"{yr:04d}-{mo:02d}",
                "start_equity": round(start_equity, 2),
                "end_equity": round(start_equity, 2),
                "n_raw": n_raw, "n_trades": 0, "n_wins": 0,
                "wr_pct": 0.0, "roi_pct": 0.0, "max_dd_pct": 0.0, "note": "skipped <10 raw",
            }
            rows.append(row)
            continue

        r = production_replay(m_trades, cfg)
        if r is None:
            row = {
                "yyyy_mm": f"{yr:04d}-{mo:02d}",
                "start_equity": round(start_equity, 2),
                "end_equity": round(start_equity, 2),
                "n_raw": n_raw, "n_trades": 0, "n_wins": 0,
                "wr_pct": 0.0, "roi_pct": 0.0, "max_dd_pct": 0.0, "note": "replay None",
            }
            rows.append(row)
            continue

        # ROI = decimal return
        roi = r.total_return  # decimal
        end_equity = start_equity * (1 + roi)
        max_dd = r.max_drawdown * 100  # %

        n_taken = r.trades
        wr = r.win_rate * 100
        n_wins = int(round(n_taken * r.win_rate))

        row = {
            "yyyy_mm": f"{yr:04d}-{mo:02d}",
            "start_equity": round(start_equity, 2),
            "end_equity": round(end_equity, 2),
            "n_raw": n_raw, "n_trades": n_taken, "n_wins": n_wins,
            "wr_pct": round(wr, 2),
            "roi_pct": round(roi * 100, 3),
            "max_dd_pct": round(max_dd, 3),
            "note": "",
        }
        rows.append(row)
        cum_trades += n_taken
        cum_wins += n_wins
        equity = end_equity

    # CSV
    CSV_OUT.parent.mkdir(parents=True, exist_ok=True)
    keys = ["yyyy_mm", "start_equity", "end_equity", "n_raw", "n_trades",
            "n_wins", "wr_pct", "roi_pct", "max_dd_pct", "note"]
    with CSV_OUT.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=keys)
        w.writeheader()
        w.writerows(rows)
    print(f"  CSV → {CSV_OUT}")

    # MD tablo
    md = ["# 15m R4 v3.1 — Aylık Full Breakdown (61 ay, compounded)\n",
          f"**Config:** risk_phoenix_scalp_15m_pyramid_r3.yaml (Pyramid + Halt OFF + cooldown 15dk YAML)",
          f"**Pool:** TOP-4 × 10 sym × 5y (n={len(pool):,})",
          f"**Initial equity:** ${INITIAL_EQUITY:,.2f}",
          f"**Final equity:** ${equity:,.2f}",
          f"**Total compound return:** {((equity/INITIAL_EQUITY)-1)*100:+,.2f}% ({equity/INITIAL_EQUITY:.2f}x)",
          f"**Total trades (executed):** {cum_trades:,}",
          f"**Overall WR:** {cum_wins/cum_trades*100:.2f}% ({cum_wins:,}/{cum_trades:,})\n",
          "## Aylık Tablo\n",
          "| YYYY-MM | Giriş ($) | Çıkış ($) | İşlem | WR% | DD% | ROI% |",
          "|---|---:|---:|---:|---:|---:|---:|"]
    for r in rows:
        md.append(f"| {r['yyyy_mm']} | {r['start_equity']:,.0f} | {r['end_equity']:,.0f} | "
                  f"{r['n_trades']} | {r['wr_pct']:.1f} | {r['max_dd_pct']:.2f} | {r['roi_pct']:+.2f} |")

    # Yearly aggregation
    md.append("\n## Yıllık Özet\n")
    md.append("| Year | Start ($) | End ($) | Annual % | Aylık mean % | Pozitif/Toplam | Neg ay |")
    md.append("|---|---:|---:|---:|---:|---:|---:|")
    yearly = {}
    for r in rows:
        yr = r["yyyy_mm"][:4]
        yearly.setdefault(yr, []).append(r)
    for yr in sorted(yearly):
        yr_rows = yearly[yr]
        y_start = yr_rows[0]["start_equity"]
        y_end = yr_rows[-1]["end_equity"]
        y_ann = (y_end / y_start - 1) * 100 if y_start > 0 else 0
        rois = [r["roi_pct"] for r in yr_rows]
        pos = sum(1 for x in rois if x > 0)
        neg = sum(1 for x in rois if x < 0)
        md.append(f"| {yr} | {y_start:,.0f} | {y_end:,.0f} | {y_ann:+.2f} | "
                  f"{sum(rois)/len(rois):+.2f} | {pos}/{len(rois)} | {neg} |")

    MD_OUT.parent.mkdir(parents=True, exist_ok=True)
    MD_OUT.write_text("\n".join(md), encoding="utf-8")
    print(f"  MD → {MD_OUT}")

    # Summary print
    print(f"\n[SUMMARY]")
    print(f"  Initial: ${INITIAL_EQUITY:,.2f}")
    print(f"  Final:   ${equity:,.2f}")
    print(f"  Total compound: {((equity/INITIAL_EQUITY)-1)*100:+,.2f}% ({equity/INITIAL_EQUITY:.2f}x)")
    print(f"  Trades:  {cum_trades:,} (wins {cum_wins:,}, WR {cum_wins/cum_trades*100:.2f}%)")
    rois = [r["roi_pct"] for r in rows]
    print(f"  Aylık mean: {sum(rois)/len(rois):+.2f}%")
    print(f"  Pozitif ay: {sum(1 for x in rois if x > 0)}/{len(rois)}")
    print(f"  Neg ay: {sum(1 for x in rois if x < 0)}/{len(rois)}")
    print(f"  Min ay: {min(rois):+.2f}%, Max ay: {max(rois):+.2f}%")


if __name__ == "__main__":
    main()
