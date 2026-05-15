"""Sec19c: IDF V3 (body>=0.50) ensemble WF + robustness.

V3 standalone PASS: n=207, mR=+0.240, p=0.060 (marjinal anlamli).
Ensemble: Champion (TOP_10+FVG) + IDF V3.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from statistics import mean, median

os.environ["PA_LOG_QUIET"] = "1"

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from price_action.backtest.lab import ProductionConfig, production_replay, _lazy_build_funding_filters
from price_action.backtest.regime import compute_btc_capitulation_halt
from scripts.v09_optimize_top10 import _gather, TOP_10
from scripts.v097_balanced_optimization import DROP_PAIRS, build_fng_short_skip


def main():
    REPORT_OUT = ROOT / "reports" / "researcher" / "sec19c_idf_v3_ensemble.md"
    out_lines = []
    def w(line=""):
        print(line)
        out_lines.append(line)

    w("# Sec19c - IDF V3 ensemble WF")
    w("")

    # Load V3 trades
    import pickle
    with open(ROOT / "reports" / "researcher" / "sec19b_best_idf.pkl", "rb") as f:
        v3 = pickle.load(f)
    idf_v3 = v3["trades"]
    print(f"IDF V3: {len(idf_v3)} trades, mR={v3['mR']:+.3f}, p={v3['p']:.3f}")
    w(f"**Variant:** V3 (body_ratio>=0.50, trend OFF)")
    w(f"**Standalone:** n={len(idf_v3)}, mR={v3['mR']:+.3f}, p={v3['p']:.3f}")
    w("")

    # Champion = TOP_10 + FVG
    print("\nGathering TOP_10 + FVG...")
    top10 = []
    for m, c in TOP_10:
        top10.extend(_gather(m, c))
    fvg = _gather("fvg_fill_reversal", "FVGFillReversalStrategy")
    champion = top10 + fvg
    print(f"TOP_10: {len(top10)}, FVG: {len(fvg)}, Champion: {len(champion)}")

    challengers = [
        ("CHAMPION (TOP_10+FVG)", champion),
        ("CHALLENGER (+IDF V3)", champion + idf_v3),
    ]
    for name, trades in challengers:
        trades.sort(key=lambda x: x["entry_ts"])

    # Filters
    print("\nFilter calendars...")
    halt_cal = compute_btc_capitulation_halt()
    fund_long, fund_short = _lazy_build_funding_filters({
        "funding_filter_enabled": True,
        "funding_aggregation_mode": "00:00_only",
    })
    fng_short_20 = build_fng_short_skip(20)
    fund_short_dict = dict(fund_short or {})
    fng_short_dict = dict(fng_short_20)
    combined_short_skip = {**fund_short_dict, **fng_short_dict}

    base_trades = challengers[-1][1]
    start = base_trades[0]["entry_ts"]
    end = base_trades[-1]["exit_ts"]
    windows = []
    cur = start
    while cur + pd.Timedelta(days=3 * 365) <= end:
        windows.append((cur, cur + pd.Timedelta(days=3 * 365)))
        cur += pd.Timedelta(days=60)
    print(f"{len(windows)} pencere (3y rolling, 60d step)")
    w(f"## 3y Rolling WF ({len(windows)} pencere)")
    w("")

    base_bal = ProductionConfig.from_yaml("configs/risk_balanced.yaml")
    cfg = base_bal.with_overrides(
        alt_data_skip_long=fund_long,
        alt_data_skip_short=combined_short_skip,
        drop_pairs=DROP_PAIRS,
    )

    w("| Senaryo | Yillik | Median | Min | Max | DD | r-adj | Negatif | Trades |")
    w("|---|---:|---:|---:|---:|---:|---:|---:|---:|")
    rated = []
    for name, trades in challengers:
        anns, dds, n_trades = [], [], []
        for ws, we in windows:
            ww = [t for t in trades if ws <= t["entry_ts"] < we]
            r = production_replay(ww, cfg)
            if r is None:
                continue
            anns.append(r.annualized(3.0) * 100)
            dds.append(r.max_drawdown * 100)
            n_trades.append(r.n_trades if hasattr(r, 'n_trades') else 0)
        if not anns:
            continue
        ma, md = mean(anns), mean(dds)
        ra = ma / abs(md) if md != 0 else 0
        neg = sum(1 for a in anns if a < 0)
        med_a = median(anns)
        avg_n = mean(n_trades) if n_trades else 0
        rated.append((name, ma, med_a, md, ra, min(anns), max(anns), neg, avg_n))
        print(f"  {name:<32}  yillik={ma:+.1f}%  med={med_a:+.1f}%  min={min(anns):+.1f}%  max={max(anns):+.1f}%  DD={md:+.1f}%  r-adj={ra:.3f}  neg={neg}  trades={avg_n:.0f}")
        w(f"| {name} | {ma:+.1f}% | {med_a:+.1f}% | {min(anns):+.1f}% | {max(anns):+.1f}% | {md:+.1f}% | {ra:.3f} | {neg} | {avg_n:.0f} |")

    w("")
    w("## Karar")
    w("")
    if len(rated) == 2:
        c, ch = rated[0], rated[1]
        d_ma = ch[1] - c[1]
        d_md = ch[3] - c[3]
        d_ra = ch[4] - c[4]
        if d_ra > 0.05 and d_ma > 0:
            verdict = "TOURNAMENT WINNER"
        elif d_ra > 0:
            verdict = "MARGINAL POSITIVE"
        elif d_ma > 0 and d_md > -2:
            verdict = "RETURN UP, RISK FLAT"
        else:
            verdict = "REJECT"
        print(f"\nVerdict: {verdict}  dYillik={d_ma:+.1f}pp  dDD={d_md:+.1f}pp  dRiskAdj={d_ra:+.3f}")
        w(f"- dYillik: {d_ma:+.1f}pp")
        w(f"- dDD: {d_md:+.1f}pp")
        w(f"- dRiskAdj: {d_ra:+.3f}")
        w(f"- **Verdict: {verdict}**")

    # Symbol-out on Champion + IDF V3
    w("")
    w("## Symbol-out CV (Champion + IDF V3)")
    w("")
    all_trades = challengers[1][1]
    symbols = sorted(set(t["symbol"] for t in all_trades))

    base_anns, base_dds = [], []
    for ws, we in windows:
        ww = [t for t in all_trades if ws <= t["entry_ts"] < we]
        r = production_replay(ww, cfg)
        if r is None:
            continue
        base_anns.append(r.annualized(3.0) * 100)
        base_dds.append(r.max_drawdown * 100)
    base_mean = mean(base_anns)
    base_dd = mean(base_dds)
    w(f"Base: {base_mean:+.1f}% / DD {base_dd:+.1f}% / r-adj {base_mean/abs(base_dd):.3f}")
    w("")
    w("| Symbol Dropped | Mean Annualized | dvsBase | DD | r-adj |")
    w("|---|---:|---:|---:|---:|")
    for sym in symbols:
        ts = [t for t in all_trades if t["symbol"] != sym]
        anns, dds = [], []
        for ws, we in windows:
            ww = [t for t in ts if ws <= t["entry_ts"] < we]
            r = production_replay(ww, cfg)
            if r is None: continue
            anns.append(r.annualized(3.0) * 100)
            dds.append(r.max_drawdown * 100)
        if not anns: continue
        ma = mean(anns)
        md = mean(dds)
        delta = ma - base_mean
        ra = ma / abs(md) if md != 0 else 0
        print(f"  drop {sym:<14} -> {ma:+.1f}% dvsBase {delta:+.1f}pp DD {md:+.1f}%")
        w(f"| -{sym} | {ma:+.1f}% | {delta:+.1f}pp | {md:+.1f}% | {ra:.3f} |")

    REPORT_OUT.parent.mkdir(parents=True, exist_ok=True)
    REPORT_OUT.write_text("\n".join(out_lines), encoding="utf-8")
    print(f"\nReport: {REPORT_OUT}")


if __name__ == "__main__":
    main()
