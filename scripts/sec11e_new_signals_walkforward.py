"""Sec11e walk-forward: TOP_10 vs TOP_10 + 2 yeni signal source.

Compares champion (v1.1.0 BALANCED+F&G+monthly_dd=0.08, yillik +%37.5,
DD -%31.8, r-adj 1.178) ile:
  - CHALLENGER A : TOP_10 + fvg_fill_reversal
  - CHALLENGER B : TOP_10 + liquidity_sweep_reversal
  - CHALLENGER C : TOP_10 + fvg + liquidity_sweep (her ikisi)

3y rolling 13 pencere walk-forward.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from statistics import mean, median

os.environ["PA_LOG_QUIET"] = "1"

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


REPORT_OUT = ROOT / "reports" / "lab" / "sec11e_new_signals.md"


def main() -> None:
    REPORT_OUT.parent.mkdir(parents=True, exist_ok=True)
    out_lines: list[str] = []

    def w(line: str = "") -> None:
        print(line)
        out_lines.append(line)

    w("# Sec11e — 3 Yeni Signal Source Survey + WF (2026-05-13)")
    w("")
    w(f"**Generated:** {pd.Timestamp.now('UTC').isoformat()}")
    w("")

    # 1) Standalone trade'leri topla (cache yoksa)
    import pickle
    pkl = ROOT / "reports" / "lab" / "sec11e_new_trades.pkl"
    if pkl.exists():
        with open(pkl, "rb") as f:
            new_trades_by_strat = pickle.load(f)
        print(f"[load] new strats from pkl: {list(new_trades_by_strat.keys())}")
    else:
        from scripts.sec11e_new_signals_standalone import NEW
        new_trades_by_strat = {}
        for m, c in NEW:
            new_trades_by_strat[m] = _gather(m, c)

    print("\nTOP_10 trade topluyor...")
    top10_trades = []
    for m, c in TOP_10:
        ts = _gather(m, c)
        top10_trades.extend(ts)
    print(f"TOP_10 toplam: {len(top10_trades)}")

    fvg = new_trades_by_strat.get("fvg_fill_reversal", [])
    liq = new_trades_by_strat.get("liquidity_sweep_reversal", [])
    print(f"FVG: {len(fvg)}, LiquiditySweep: {len(liq)}")

    # Edge gate yorumu
    w("## Standalone Edge (5y, 11 sym)")
    w("")
    w("| Strategy | n | mR | sumR | WR | Edge gate (mR>+0.10, n>50, WR>35%) |")
    w("|---|---:|---:|---:|---:|---|")
    import numpy as np
    for name, trades in [("fvg_fill_reversal", fvg),
                          ("liquidity_sweep_reversal", liq),
                          ("nr7_breakout_v2", new_trades_by_strat.get("nr7_breakout_v2", []))]:
        if not trades:
            w(f"| {name} | 0 | - | - | - | n/a |")
            continue
        Rs = np.array([t["R"] for t in trades])
        mR = float(Rs.mean())
        sumR = float(Rs.sum())
        WR = float((Rs > 0).mean())
        passes = mR > 0.10 and len(trades) > 50 and WR > 0.35
        verdict = "PASS" if passes else "FAIL"
        w(f"| {name} | {len(trades)} | {mR:+.3f} | {sumR:+.1f} | {WR*100:.1f}% | **{verdict}** |")
    w("")

    # 2) Walk-forward
    challengers = [
        ("CHAMPION (TOP_10)",                    top10_trades),
        ("CHALLENGER A (TOP_10 + FVG)",          top10_trades + fvg),
        ("CHALLENGER B (TOP_10 + LiquiditySweep)", top10_trades + liq),
        ("CHALLENGER C (TOP_10 + FVG + LiqSweep)", top10_trades + fvg + liq),
    ]

    # Sort all
    for name, trades in challengers:
        trades.sort(key=lambda x: x["entry_ts"])

    # Filter calendars
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

    # Pencere
    base_trades = challengers[3][1]
    start = base_trades[0]["entry_ts"]
    end = base_trades[-1]["exit_ts"]
    windows = []
    cur = start
    while cur + pd.Timedelta(days=3 * 365) <= end:
        windows.append((cur, cur + pd.Timedelta(days=3 * 365)))
        cur += pd.Timedelta(days=60)
    print(f"Pencere sayisi: {len(windows)} (3y rolling, 60 gun step)")
    w(f"## Walk-Forward (3y rolling, {len(windows)} pencere)")
    w("")

    base_bal = ProductionConfig.from_yaml("configs/risk_balanced.yaml")
    overrides = dict(
        alt_data_skip_long=fund_long,
        alt_data_skip_short=combined_short_skip,
        drop_pairs=DROP_PAIRS,
    )
    cfg = base_bal.with_overrides(**overrides)

    w(f"| Senaryo | Yillik | Median | Min | Max | DD | r-adj | Negatif | Trades |")
    w(f"|---|---:|---:|---:|---:|---:|---:|---:|---:|")

    print(f"\n{'scenario':<48}  {'yillik':>8}  {'med':>7}  {'min':>7}  {'max':>7}  {'DD':>6}  {'r-adj':>7}  {'neg':>4}  {'trades':>7}")
    print("-" * 115)

    rated = []
    for name, trades in challengers:
        anns, dds, n_trades = [], [], []
        for ws, we in windows:
            ww_trades = [t for t in trades if ws <= t["entry_ts"] < we]
            r = production_replay(ww_trades, cfg)
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
        print(f"  {name:<48}  {ma:>+6.1f}%  {med_a:>+5.1f}%  {min(anns):>+5.1f}%  {max(anns):>+5.1f}%  {md:>+4.0f}%  {ra:>6.3f}  {neg:>3}  {avg_n:>6.0f}")
        w(f"| {name} | {ma:+.1f}% | {med_a:+.1f}% | {min(anns):+.1f}% | {max(anns):+.1f}% | {md:+.1f}% | {ra:.3f} | {neg} | {avg_n:.0f} |")

    w("")
    w("## Karar Karsilastirmasi")
    w("")
    if rated:
        c = rated[0]  # CHAMPION
        for ch in rated[1:]:
            d_ma = ch[1] - c[1]
            d_md = ch[3] - c[3]
            d_ra = ch[4] - c[4]
            verdict = "MARGINAL"
            if d_ra > 0.05 and d_ma > 0:
                verdict = "TOURNAMENT WINNER"
            elif d_ra > 0:
                verdict = "MARGINAL POSITIVE"
            elif d_ma > 0 and d_md > -2:
                verdict = "RETURN UP, RISK FLAT"
            else:
                verdict = "REJECT"
            w(f"- **{ch[0]}** vs Champion: dYillik {d_ma:+.1f}pp, dDD {d_md:+.1f}pp, dRiskAdj {d_ra:+.3f} -> **{verdict}**")

    w("")
    w("## Reproducibility")
    w("")
    w(f"- TOP_10 trades: {len(top10_trades)}")
    w(f"- FVG trades: {len(fvg)}")
    w(f"- LiquiditySweep trades: {len(liq)}")
    w(f"- Drop pairs: {len(DROP_PAIRS)}")
    w(f"- Funding short-skip gun: {len(fund_short or {})}, F&G short-skip: {len(fng_short_20)}")
    w(f"- Pencere: {len(windows)} (3y rolling)")
    w(f"- Config: configs/risk_balanced.yaml (monthly_dd=0.08)")

    REPORT_OUT.write_text("\n".join(out_lines), encoding="utf-8")
    print(f"\nRapor: {REPORT_OUT}")


if __name__ == "__main__":
    main()
