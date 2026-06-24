"""SEC46: 5m TOP-2 Per-Calendar-Month P&L (60 ay).

User aylık breakdown istedi. Pool cached (sec44), sadece per-month
production_replay döngüsü. ~5-10 dk.

Output: reports/lab/sec46_phoenix_scalp_5m_per_month_results.md
"""
from __future__ import annotations

import io
import os
import pickle
import sys
from datetime import datetime, timezone
from pathlib import Path

if __name__ == "__main__":
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
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

CACHE = ROOT / "data" / "sec44_5m_top2_pool.pkl"
REPORT = ROOT / "reports" / "lab" / "sec46_phoenix_scalp_5m_per_month_results.md"
RISK_YAML = ROOT / "configs" / "risk_phoenix_scalp_5m.yaml"

import pandas as pd
from price_action.backtest.lab import ProductionConfig, production_replay


def to_utc(ts):
    return ts.replace(tzinfo=timezone.utc) if ts.tzinfo is None else ts.astimezone(timezone.utc)


def main():
    if not CACHE.exists():
        print(f"ERROR: pool cache missing: {CACHE}")
        return
    print(f"[LOAD] {CACHE} ({CACHE.stat().st_size/1e6:.1f} MB)", flush=True)
    with CACHE.open("rb") as fh:
        pool = pickle.load(fh)
    print(f"[POOL] {len(pool):,} trade, mR {sum(t['R'] for t in pool)/len(pool):+.3f}", flush=True)

    cfg = ProductionConfig.from_yaml(str(RISK_YAML))
    print(f"[YAML] {RISK_YAML.name} (daily_loss_pct varies — check current)", flush=True)

    pool.sort(key=lambda x: x["entry_ts"])
    start_dt = to_utc(pool[0]["entry_ts"])
    end_dt = to_utc(pool[-1]["entry_ts"])

    # Generate month buckets (UTC year-month tuples)
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

    print(f"[MONTHS] {len(months)} ay analiz edilecek\n", flush=True)
    print(f"| Ay | n trade | mean R | Monthly % | DD % | r-adj | WR % |")
    print(f"|---|---:|---:|---:|---:|---:|---:|")

    results = []
    for yr, mo, ms, me in months:
        m_trades = [t for t in pool if ms <= to_utc(t["entry_ts"]) < me]
        if len(m_trades) < 10:
            print(f"| {yr}-{mo:02d} | {len(m_trades)} | - | (n<10 skip) | - | - | - |")
            continue
        r = production_replay(m_trades, cfg)
        if r is None:
            print(f"| {yr}-{mo:02d} | {len(m_trades)} | - | (replay None) | - | - | - |")
            continue
        # Monthly raw return (compound): total_return = final/initial - 1
        ret_pct = r.total_return * 100
        dd_pct = r.max_drawdown * 100
        ra = ret_pct / abs(dd_pct) if dd_pct != 0 else 0
        Rs = [t["R"] for t in m_trades]
        mR = sum(Rs) / len(Rs)
        wr = sum(1 for x in Rs if x > 0) / len(Rs) * 100
        results.append((yr, mo, len(m_trades), mR, ret_pct, dd_pct, ra, wr))
        print(f"| {yr}-{mo:02d} | {len(m_trades):,} | {mR:+.3f} | {ret_pct:+.1f}% | {dd_pct:+.1f}% | {ra:.2f} | {wr:.1f}% |")

    if results:
        rets = [r[4] for r in results]
        dds = [r[5] for r in results]
        ras = [r[6] for r in results]
        pos = sum(1 for r in rets if r > 0)
        neg = sum(1 for r in rets if r <= 0)
        print(f"\n--- ÖZET ({len(results)} ay) ---")
        print(f"Aylık mean: {sum(rets)/len(rets):+.2f}%  |  median: {sorted(rets)[len(rets)//2]:+.2f}%")
        print(f"Aylık min : {min(rets):+.2f}%  |  max: {max(rets):+.2f}%")
        print(f"DD mean : {sum(dds)/len(dds):+.2f}%  |  worst: {min(dds):+.2f}%")
        print(f"Pozitif ay: {pos}/{len(results)} ({pos/len(results)*100:.0f}%)")
        print(f"Negatif ay: {neg}/{len(results)}")
        if len(rets) > 1:
            mu = sum(rets) / len(rets)
            std = (sum((x - mu) ** 2 for x in rets) / (len(rets) - 1)) ** 0.5
            cv = std / abs(mu) if mu != 0 else 0
            print(f"Std: {std:.2f}pp  |  CV: {cv*100:.0f}%")

    # Markdown rapor
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    out = []
    out.append(f"# SEC46: Phoenix-Scalp 5m TOP-2 — Per-Month P&L\n")
    out.append(f"**Generated:** {datetime.now().isoformat()}\n")
    out.append(f"**YAML:** `{RISK_YAML.name}` (post SEC45-A1 fix daily_loss_pct=0.03)\n")
    out.append(f"**Pool:** {len(pool):,} trade\n\n")
    out.append(f"## {len(results)} Aylık Breakdown\n\n")
    out.append(f"| Ay | n trade | mean R | Monthly % | DD % | r-adj | WR % |\n")
    out.append(f"|---|---:|---:|---:|---:|---:|---:|\n")
    for r in results:
        out.append(f"| {r[0]}-{r[1]:02d} | {r[2]:,} | {r[3]:+.3f} | {r[4]:+.1f}% | {r[5]:+.1f}% | {r[6]:.2f} | {r[7]:.1f}% |\n")
    if results:
        rets = [r[4] for r in results]
        dds = [r[5] for r in results]
        out.append(f"\n## Özet\n")
        mu = sum(rets) / len(rets)
        std = (sum((x - mu) ** 2 for x in rets) / (len(rets) - 1)) ** 0.5 if len(rets) > 1 else 0
        cv = std / abs(mu) if mu != 0 else 0
        out.append(f"- Aylık mean: **{mu:+.2f}%**  | median {sorted(rets)[len(rets)//2]:+.2f}%\n")
        out.append(f"- Aylık min: **{min(rets):+.2f}%**  | max **{max(rets):+.2f}%**\n")
        out.append(f"- DD mean: {sum(dds)/len(dds):+.2f}%  | worst {min(dds):+.2f}%\n")
        out.append(f"- Pozitif ay: **{sum(1 for r in rets if r>0)}/{len(rets)}** ({sum(1 for r in rets if r>0)/len(rets)*100:.0f}%)\n")
        out.append(f"- Std: {std:.2f}pp, **CV: {cv*100:.0f}%**\n")
    REPORT.write_text("".join(out), encoding="utf-8")
    print(f"\n[DONE] {REPORT}")


if __name__ == "__main__":
    main()
