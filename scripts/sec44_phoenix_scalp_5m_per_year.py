"""SEC44: 5m TOP-2 Per-Calendar-Year P&L Analysis.

Önceki sec43 v1+v2 build_windows monkey-patch'i çalışmadı (default param bind
issue). Doğru çözüm: trade pool'u TAKVİM YILINA göre grupla, her yıl için
production_replay çağır. Override-free, deterministic.

Cevaplar:
- 2021-05/2022-05: yıllık % / DD
- 2022-05/2023-05: ...
- 2023-05/2024-05: ...
- 2024-05/2025-05: ...
- 2025-05/2026-05: ...

5 bağımsız yıllık gözlem. İstikrar mı volatilite mi user gözüyle gösterilecek.

Output: reports/lab/sec44_phoenix_scalp_5m_per_year_results.md
Cache: data/sec44_5m_top2_pool.pkl (re-collect avoid)
"""
from __future__ import annotations

import io
import os
import pickle
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean, median

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

import scripts.sec31_phoenix_scalp_15m_rolling as sec31
import scripts.sec32_phoenix_scalp_5m_rolling as sec32

CACHE = ROOT / "data" / "sec44_5m_top2_pool.pkl"
REPORT = ROOT / "reports" / "lab" / "sec44_phoenix_scalp_5m_per_year_results.md"

SYMBOLS_10 = sec32.SYMBOLS_10  # Phoenix 10 sym
STRATS = [
    ("vsa_climax_test", "VSAClimaxTestStrategy"),
    ("brooks_failed_breakout", "BrooksFailedBreakoutStrategy"),
]


def collect_or_cache() -> list[dict]:
    if CACHE.exists():
        print(f"[CACHE HIT] {CACHE} ({CACHE.stat().st_size/1e6:.1f} MB)", flush=True)
        with CACHE.open("rb") as fh:
            return pickle.load(fh)
    sec32.PHOENIX_STRATEGIES = STRATS
    print(f"[COLLECT] 2 strat × 10 sym × 5y 5m — beklenen ~20 dk", flush=True)
    t0 = time.time()
    pool = sec32.collect_all_trades(SYMBOLS_10, parallel=False)
    print(f"[COLLECT DONE] {len(pool)} trade, {(time.time()-t0)/60:.1f} dk", flush=True)
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    with CACHE.open("wb") as fh:
        pickle.dump(pool, fh)
    print(f"[CACHED] {CACHE.stat().st_size/1e6:.1f} MB", flush=True)
    return pool


def main() -> None:
    pool = collect_or_cache()
    if not pool:
        print("EMPTY POOL")
        return

    pool.sort(key=lambda x: x["entry_ts"])
    print(f"\nPool range: {pool[0]['entry_ts']} → {pool[-1]['entry_ts']}")
    print(f"Pool size: {len(pool):,}")
    print(f"Pool mR : {sum(t['R'] for t in pool)/len(pool):+.3f}")

    # Risk config load
    from price_action.backtest.lab import ProductionConfig, production_replay
    risk_yaml = ROOT / "configs" / "risk_phoenix_scalp_5m.yaml"
    cfg = ProductionConfig.from_yaml(str(risk_yaml))
    print(f"\nRisk YAML: {risk_yaml.name}")

    # Yıllık bucket (UTC anchored)
    # 5y data: ~2021-05-16 → 2026-05-16. 5 calendar years (Mayıs anchored, non-overlapping).
    pool_start = pool[0]["entry_ts"].replace(tzinfo=timezone.utc) if pool[0]["entry_ts"].tzinfo is None else pool[0]["entry_ts"].astimezone(timezone.utc)
    pool_end = pool[-1]["entry_ts"].replace(tzinfo=timezone.utc) if pool[-1]["entry_ts"].tzinfo is None else pool[-1]["entry_ts"].astimezone(timezone.utc)

    print(f"\n--- 5 BAĞIMSIZ YIL (Mayıs-Mayıs, non-overlapping) ---\n")
    print(f"| Yıl | Start | End | n trade | Mean R | Annual % | DD % | r-adj | WR % |")
    print(f"|---|---|---|---:|---:|---:|---:|---:|---:|")

    import pandas as pd
    yearly_results = []
    for y_offset in range(5):
        y_start = pool_start + pd.Timedelta(days=365 * y_offset)
        y_end = y_start + pd.Timedelta(days=365)
        if y_end > pool_end:
            y_end = pool_end + pd.Timedelta(days=1)
        # Trade filter (entry_ts in [y_start, y_end))
        y_trades = [t for t in pool if y_start <= (t["entry_ts"].replace(tzinfo=timezone.utc) if t["entry_ts"].tzinfo is None else t["entry_ts"].astimezone(timezone.utc)) < y_end]
        if not y_trades:
            print(f"| Y{y_offset+1} | {y_start.date()} | {y_end.date()} | 0 | - | - | - | - | - |")
            continue
        r = production_replay(y_trades, cfg)
        if r is None:
            print(f"| Y{y_offset+1} | {y_start.date()} | {y_end.date()} | {len(y_trades)} | - | (replay None) | - | - | - |")
            continue
        # 1-yıllık pencere için annualization period_years = 1.0
        ann = r.annualized(1.0) * 100
        dd = r.max_drawdown * 100
        ra = ann / abs(dd) if dd != 0 else 0
        Rs = [t["R"] for t in y_trades]
        mR = sum(Rs) / len(Rs)
        wr = sum(1 for r0 in Rs if r0 > 0) / len(Rs) * 100
        row = (y_offset+1, y_start.date(), y_end.date(), len(y_trades), mR, ann, dd, ra, wr)
        yearly_results.append(row)
        print(f"| Y{y_offset+1} | {y_start.date()} | {y_end.date()} | {len(y_trades):,} | {mR:+.3f} | {ann:+.1f}% | {dd:+.1f}% | {ra:.3f} | {wr:.1f}% |")

    if yearly_results:
        anns = [r[5] for r in yearly_results]
        dds = [r[6] for r in yearly_results]
        ras = [r[7] for r in yearly_results]
        print(f"\n--- ÖZET (5 bağımsız yıl) ---")
        print(f"Yıllık mean: {sum(anns)/len(anns):+.1f}% | median {sorted(anns)[len(anns)//2]:+.1f}%")
        print(f"Yıllık min:  {min(anns):+.1f}% | max {max(anns):+.1f}%")
        print(f"DD     mean: {sum(dds)/len(dds):+.1f}% | min {min(dds):+.1f}% | max {max(dds):+.1f}%")
        print(f"r-adj  mean: {sum(ras)/len(ras):.3f}")
        # std
        if len(anns) > 1:
            mu = sum(anns)/len(anns)
            std = (sum((a-mu)**2 for a in anns) / (len(anns)-1)) ** 0.5
            cv = std / abs(mu) if mu != 0 else 0
            print(f"Yıllık std:  {std:.1f}pp  (CV = {cv*100:.1f}%)  → CV<%30 istikrarlı, >%100 volatil")

    # Markdown report yaz
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    out = []
    out.append(f"# SEC44: Phoenix-Scalp 5m TOP-2 — Per-Year P&L (Non-Overlapping)\n")
    out.append(f"**Generated:** {datetime.now().isoformat()}\n")
    out.append(f"**Pool:** {len(pool):,} trade, mR {sum(t['R'] for t in pool)/len(pool):+.3f}\n\n")
    out.append(f"## 5 Bağımsız Takvim Yılı\n\n")
    out.append(f"| Yıl | Start | End | n trade | Mean R | Annual % | DD % | r-adj | WR % |\n")
    out.append(f"|---|---|---|---:|---:|---:|---:|---:|---:|\n")
    for row in yearly_results:
        out.append(f"| Y{row[0]} | {row[1]} | {row[2]} | {row[3]:,} | {row[4]:+.3f} | {row[5]:+.1f}% | {row[6]:+.1f}% | {row[7]:.3f} | {row[8]:.1f}% |\n")
    if yearly_results:
        anns = [r[5] for r in yearly_results]
        dds = [r[6] for r in yearly_results]
        mu = sum(anns)/len(anns)
        std = (sum((a-mu)**2 for a in anns) / (len(anns)-1)) ** 0.5 if len(anns)>1 else 0
        cv = std/abs(mu) if mu != 0 else 0
        out.append(f"\n## Özet\n")
        out.append(f"- Yıllık mean: **{mu:+.1f}%** | median {sorted(anns)[len(anns)//2]:+.1f}%\n")
        out.append(f"- Yıllık min: **{min(anns):+.1f}%** | max **{max(anns):+.1f}%**\n")
        out.append(f"- DD mean: **{sum(dds)/len(dds):+.1f}%** | min {min(dds):+.1f}% | max {max(dds):+.1f}%\n")
        out.append(f"- Yıllık std: {std:.1f}pp, **CV (coefficient of variation): {cv*100:.1f}%**\n")
        out.append(f"\n**İstikrar yorumu:** CV < %30 istikrarlı, %30-%100 orta, > %100 volatil.\n")
    REPORT.write_text("".join(out), encoding="utf-8")
    print(f"\n[DONE] {REPORT}")


if __name__ == "__main__":
    main()
