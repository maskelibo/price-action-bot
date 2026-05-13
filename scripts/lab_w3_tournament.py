"""Lab W3 Tournament — Champion vs Challenger A/B (Sec3.2).

3 senaryo karsilastirma (3y rolling pencere):
  CHAMPION (v0.9.7): BALANCED + funding + drop_pairs + F&G short-skip
  CHALLENGER A:      Flat T2 (her trade %2 risk + 2x lev, hicbir filter)
  CHALLENGER B:      BALANCED + funding + drop_pairs (F&G yok — F&G katkisini izole)

Output: reports/lab/w3_tournament_2026-05-16.md
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from statistics import mean, median, stdev

os.environ["PA_LOG_QUIET"] = "1"

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from price_action.backtest.lab import ProductionConfig, production_replay, _lazy_build_funding_filters
from price_action.backtest.regime import compute_btc_capitulation_halt
from scripts.v09_optimize_top10 import _gather, TOP_10
from scripts.v097_balanced_optimization import DROP_PAIRS, build_fng_short_skip

REPORT_OUT = ROOT / "reports" / "lab" / "w3_tournament_2026-05-16.md"


def main() -> None:
    REPORT_OUT.parent.mkdir(parents=True, exist_ok=True)
    out_lines: list[str] = []

    def w(line: str = "") -> None:
        print(line)
        out_lines.append(line)

    w("# Lab W3 Tournament — 2026-05-16")
    w("")
    w(f"**Generated:** {pd.Timestamp.utcnow().isoformat()}")
    w("")
    w("## Adaylar")
    w("")
    w("- **CHAMPION (v0.9.7 production lock):** BALANCED + funding + drop_pairs + F&G short-skip")
    w("- **CHALLENGER A:** Flat T2 (her trade %2 risk + 2x lev, hicbir filter — EER v1 yan-bulgu)")
    w("- **CHALLENGER B:** BALANCED + funding + drop_pairs (F&G yok — F&G katkisinin izole testi)")
    w("")
    w("**Yontem:** 3y rolling 13 pencere walk-forward (2021-05-15 -> 2026-05-08).")
    w("Karsilastirma metric'leri: yillik return, max DD, risk-adj (return/abs(DD)), min/max pencere.")
    w("")

    print("Trade topluyor...")
    all_trades = []
    for m, c in TOP_10:
        all_trades.extend(_gather(m, c))
    all_trades.sort(key=lambda x: x["entry_ts"])
    w(f"**Trade pool:** {len(all_trades)}")

    print("Filter calendars...")
    halt_cal = compute_btc_capitulation_halt()
    fund_long, fund_short = _lazy_build_funding_filters({
        "funding_filter_enabled": True,
        "funding_aggregation_mode": "00:00_only",
    })
    fng_short_20 = build_fng_short_skip(20)
    fund_short_dict = dict(fund_short or {})
    fng_short_dict = dict(fng_short_20)
    combined_short_skip = {**fund_short_dict, **fng_short_dict}

    # Pencere yapisi
    start = all_trades[0]["entry_ts"]
    end = all_trades[-1]["exit_ts"]
    windows = []
    cur = start
    while cur + pd.Timedelta(days=3 * 365) <= end:
        windows.append((cur, cur + pd.Timedelta(days=3 * 365)))
        cur += pd.Timedelta(days=60)
    w(f"**Pencere sayisi:** {len(windows)} (3y rolling, 60 gun step)")
    w("")

    # Configs
    base_bal = ProductionConfig.from_yaml("configs/risk_balanced.yaml")

    # Flat T2: %2 fix risk, 2x lev, no filters, no halt
    # Mevcut ProductionConfig.with_overrides ile: risk_pct=0.02, capitulation_halt off,
    # alt_data_skip = None, drop_pairs = empty
    flat_t2 = base_bal.with_overrides(
        risk_pct=0.020,
        # tum filter'lari kapat
        alt_data_skip_long=None,
        alt_data_skip_short=None,
        drop_pairs=frozenset(),
    )
    # Flat T2 icin halt'i kapatmak gerekirse — risk_balanced'de varsa:
    if hasattr(flat_t2, "with_overrides") and "capitulation_halt_enabled" in dir(flat_t2):
        try:
            flat_t2 = flat_t2.with_overrides(capitulation_halt_enabled=False)
        except Exception:
            pass

    scenarios = [
        ("CHAMPION (v0.9.7)",
         base_bal.with_overrides(
             alt_data_skip_long=fund_long,
             alt_data_skip_short=combined_short_skip,
             drop_pairs=DROP_PAIRS,
         )),
        ("CHALLENGER A: Flat T2",
         flat_t2),
        ("CHALLENGER B: BALANCED+funding+drop_pairs (F&G yok)",
         base_bal.with_overrides(
             alt_data_skip_long=fund_long,
             alt_data_skip_short=fund_short,
             drop_pairs=DROP_PAIRS,
         )),
    ]

    w("## Sonuclar")
    w("")
    w(f"| Senaryo | Yillik | Median | Min | Max | DD | MinDD | r-adj | Negatif |")
    w(f"|---|---:|---:|---:|---:|---:|---:|---:|---:|")

    rated = []
    print(f"\n{'scenario':<54}  {'yillik':>8}  {'med':>7}  {'min':>7}  {'max':>7}  {'DD':>6}  {'minDD':>7}  {'r-adj':>7}  {'neg':>4}")
    print("-" * 120)
    for name, cfg in scenarios:
        anns, dds = [], []
        for ws, we in windows:
            ww_trades = [t for t in all_trades if ws <= t["entry_ts"] < we]
            r = production_replay(ww_trades, cfg)
            if r is None:
                continue
            anns.append(r.annualized(3.0) * 100)
            dds.append(r.max_drawdown * 100)
        if not anns:
            continue
        ma, md = mean(anns), mean(dds)
        ra = ma / abs(md) if md != 0 else 0
        neg = sum(1 for a in anns if a < 0)
        med_a = median(anns)
        rated.append((name, ma, med_a, md, ra, min(anns), max(anns), min(dds), neg))
        print(f"  {name:<54}  {ma:>+6.1f}%  {med_a:>+5.1f}%  {min(anns):>+5.1f}%  {max(anns):>+5.1f}%  {md:>+4.0f}%  {min(dds):>+5.0f}%  {ra:>6.3f}  {neg:>3}")
        w(f"| {name} | {ma:+.1f}% | {med_a:+.1f}% | {min(anns):+.1f}% | {max(anns):+.1f}% | {md:+.1f}% | {min(dds):+.1f}% | {ra:.3f} | {neg} |")

    w("")
    w("## Karar")
    w("")
    if not rated:
        w("**HATA:** Hicbir senaryo calismadi.")
    else:
        # Champion delta
        champion = rated[0]
        c_name, c_ma, c_med, c_md, c_ra, c_min, c_max, c_mind, c_neg = champion
        w(f"**Champion baseline:** {c_name} — yillik {c_ma:+.1f}%, DD {c_md:+.1f}%, r-adj {c_ra:.3f}")
        w("")
        w(f"| Aday | yillik delta | DD delta | r-adj delta | verdict |")
        w(f"|---|---:|---:|---:|---|")
        winners: list[tuple] = []
        for r in rated[1:]:
            n, ma, med, md, ra, mna, mxa, mnd, neg = r
            d_ma = ma - c_ma
            d_md = md - c_md
            d_ra = ra - c_ra
            verdict = ""
            if d_ra > 0.05:
                verdict = "**CHAMPION YENILDI** (r-adj artisi)"
                winners.append(r)
            elif d_ra > 0:
                verdict = "marjinal (r-adj +)"
            elif d_ma > 0 and d_md > 0:
                verdict = "ROI+ DD+ ama r-adj-"
            else:
                verdict = "champion korundu"
            w(f"| {n} | {d_ma:+.1f}pp | {d_md:+.1f}pp | {d_ra:+.3f} | {verdict} |")

        w("")
        if winners:
            w(f"**TOURNAMENT WINNER:** {winners[0][0]} (r-adj +{winners[0][4] - c_ra:.3f})")
            w(f"-> v1.1 release degerlendirilebilir, manual onay gerekli.")
        else:
            w(f"**CHAMPION CONFIRMED:** v0.9.7 BALANCED+funding+drop_pairs+F&G korundu.")
            w(f"-> Production lock devam, v1.1 *yok* (sadece tournament confirmation tag).")

    w("")
    w("## Reproducibility")
    w("")
    w(f"- Trade pool size: {len(all_trades)}")
    w(f"- Halt calendar gun sayisi: {sum(1 for v in halt_cal.values() if v)}")
    w(f"- Funding short-skip gun: {len(fund_short or {})}, F&G short-skip: {len(fng_short_20)}")
    w(f"- Drop pairs: {len(DROP_PAIRS)}")
    w(f"- 3y rolling pencere: {len(windows)}")

    REPORT_OUT.write_text("\n".join(out_lines), encoding="utf-8")
    print(f"\nRapor: {REPORT_OUT}")


if __name__ == "__main__":
    main()
