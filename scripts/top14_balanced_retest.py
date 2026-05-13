"""TOP_14 BALANCED Retest — TOP_10'a 4 yeni POZITIF stratejiyi ekleyip champion ile karsilastir.

Yeni eklemeler (Sec4.1 survey'den POZITIF):
  + vol_risk_premium       (VRP overlay, mR +1.80, n=32)
  + naked_poc_mr           (POC MR, mR +0.35, n=101)
  + failed_bo_bos_reclaim  (failed BO+BOS, mR +0.13, n=325)
  + ii_breakout            (II breakout, mR +0.17, n=64)

Senaryolar:
  CHAMPION (v0.9.7): TOP_10 + BALANCED+funding+drop_pairs+F&G
  CHALLENGER C: TOP_14 (TOP_10 + 4 yeni) + BALANCED+funding+drop_pairs+F&G
  CHALLENGER D: TOP_14 + BALANCED+funding+drop_pairs+F&G + drop_pairs guncellenmis (yeni stratejilerin kotu sembolleri otomatik test)

3y rolling 13 pencere walk-forward.
Output: reports/lab/top14_retest_2026-05-13.md
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

from price_action.backtest.lab import ProductionConfig, production_replay, _lazy_build_funding_filters
from price_action.backtest.regime import compute_btc_capitulation_halt
from scripts.v09_optimize_top10 import _gather, TOP_10
from scripts.v097_balanced_optimization import DROP_PAIRS, build_fng_short_skip

NEW_STRATS = [
    ("vol_risk_premium", "VolRiskPremiumStrategy"),
    ("naked_poc_mr", "NakedPOCMrStrategy"),
    ("failed_bo_bos_reclaim", "FailedBreakoutBOSReclaimStrategy"),
    ("ii_breakout", "IIBreakoutStrategy"),
]

# 4 yeni strateji icin sinif adi tahmini bul
def find_class_in_module(module_name: str, default: str) -> str:
    try:
        mod = __import__(f"price_action.strategies.{module_name}", fromlist=["*"])
    except Exception:
        return default
    if hasattr(mod, default):
        return default
    for name in dir(mod):
        if name.endswith("Strategy") and not name.startswith("_"):
            return name
    return default


REPORT_OUT = ROOT / "reports" / "lab" / "top14_retest_2026-05-13.md"


def main() -> None:
    REPORT_OUT.parent.mkdir(parents=True, exist_ok=True)
    out_lines: list[str] = []

    def w(line: str = "") -> None:
        print(line)
        out_lines.append(line)

    w("# TOP_14 BALANCED Retest — 2026-05-13")
    w("")
    w(f"**Generated:** {pd.Timestamp.now('UTC').isoformat()}")
    w("")
    w("## Yeni Strateji Eklemeleri (Sec4.1 survey'den POZITIF)")
    w("")
    w("- vol_risk_premium  (mR +1.80, n=32)")
    w("- naked_poc_mr      (mR +0.35, n=101)")
    w("- failed_bo_bos_reclaim (mR +0.13, n=325)")
    w("- ii_breakout       (mR +0.17, n=64)")
    w("")

    # Sinif adlarini cozumle
    new_strats_resolved = []
    for module_name, default_cls in NEW_STRATS:
        cls_name = find_class_in_module(module_name, default_cls)
        new_strats_resolved.append((module_name, cls_name))
        print(f"  resolved: {module_name} -> {cls_name}")

    # Trade'leri topla
    print("\nTrade topluyor (TOP_10 + 4 yeni)...")
    all_trades_top10 = []
    for m, c in TOP_10:
        ts = _gather(m, c)
        all_trades_top10.extend(ts)
        print(f"  {m}: {len(ts)}")

    new_trades = []
    for m, c in new_strats_resolved:
        ts = _gather(m, c)
        new_trades.extend(ts)
        print(f"  {m}: {len(ts)}")

    all_trades_top14 = all_trades_top10 + new_trades
    all_trades_top10.sort(key=lambda x: x["entry_ts"])
    all_trades_top14.sort(key=lambda x: x["entry_ts"])

    w(f"**TOP_10 trade pool:** {len(all_trades_top10)}")
    w(f"**TOP_14 trade pool:** {len(all_trades_top14)} (+{len(new_trades)})")

    # Filter calendars
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
    start = all_trades_top14[0]["entry_ts"]
    end = all_trades_top14[-1]["exit_ts"]
    windows = []
    cur = start
    while cur + pd.Timedelta(days=3 * 365) <= end:
        windows.append((cur, cur + pd.Timedelta(days=3 * 365)))
        cur += pd.Timedelta(days=60)
    w(f"**Pencere sayisi:** {len(windows)} (3y rolling, 60 gun step)")
    w("")

    base_bal = ProductionConfig.from_yaml("configs/risk_balanced.yaml")
    overrides = dict(
        alt_data_skip_long=fund_long,
        alt_data_skip_short=combined_short_skip,
        drop_pairs=DROP_PAIRS,
    )

    scenarios = [
        ("CHAMPION (TOP_10 + BALANCED+F&G)",
         all_trades_top10,
         base_bal.with_overrides(**overrides)),
        ("CHALLENGER C (TOP_14 + BALANCED+F&G)",
         all_trades_top14,
         base_bal.with_overrides(**overrides)),
    ]

    w("## Sonuclar")
    w("")
    w(f"| Senaryo | Yillik | Median | Min | Max | DD | r-adj | Negatif |")
    w(f"|---|---:|---:|---:|---:|---:|---:|---:|")

    print(f"\n{'scenario':<55}  {'yillik':>8}  {'med':>7}  {'min':>7}  {'max':>7}  {'DD':>6}  {'r-adj':>7}  {'neg':>4}")
    print("-" * 115)

    rated = []
    for name, trades, cfg in scenarios:
        anns, dds = [], []
        for ws, we in windows:
            ww_trades = [t for t in trades if ws <= t["entry_ts"] < we]
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
        rated.append((name, ma, med_a, md, ra, min(anns), max(anns), neg))
        print(f"  {name:<55}  {ma:>+6.1f}%  {med_a:>+5.1f}%  {min(anns):>+5.1f}%  {max(anns):>+5.1f}%  {md:>+4.0f}%  {ra:>6.3f}  {neg:>3}")
        w(f"| {name} | {ma:+.1f}% | {med_a:+.1f}% | {min(anns):+.1f}% | {max(anns):+.1f}% | {md:+.1f}% | {ra:.3f} | {neg} |")

    w("")
    w("## Karar")
    w("")
    if len(rated) < 2:
        w("**HATA:** Karsilastirma icin yeterli senaryo yok.")
    else:
        c_name, c_ma, c_med, c_md, c_ra, c_min, c_max, c_neg = rated[0]
        ch_name, ch_ma, ch_med, ch_md, ch_ra, ch_min, ch_max, ch_neg = rated[1]
        d_ma = ch_ma - c_ma
        d_md = ch_md - c_md
        d_ra = ch_ra - c_ra
        w(f"**Champion:** {c_name} — yillik {c_ma:+.1f}%, DD {c_md:+.1f}%, r-adj {c_ra:.3f}")
        w(f"**Challenger:** {ch_name} — yillik {ch_ma:+.1f}%, DD {ch_md:+.1f}%, r-adj {ch_ra:.3f}")
        w(f"**Delta:** yillik {d_ma:+.1f}pp, DD {d_md:+.1f}pp, r-adj {d_ra:+.3f}")
        w("")
        if d_ra > 0.05:
            w(f"**TOURNAMENT WINNER:** TOP_14 yenildi -> v1.1 release adayi")
        elif d_ra > 0:
            w("**MARJINAL:** r-adj artisi var ama 0.05 esiginin altinda — paper trading ile dogrulamali")
        elif d_ma > 0 and d_md > 0:
            w("**WIN-WIN ama r-adj-:** ROI ve DD ikisi de iyilesti ama r-adj duzeyi dustu (atypik)")
        else:
            w("**CHAMPION CONFIRMED:** TOP_10 daha iyi/esit, yeni stratejiler net edge eklemiyor")

    w("")
    w("## Reproducibility")
    w("")
    w(f"- TOP_10 trades: {len(all_trades_top10)}")
    w(f"- New 4 strats trades: {len(new_trades)}")
    w(f"- TOP_14 total: {len(all_trades_top14)}")
    w(f"- Drop pairs: {len(DROP_PAIRS)}")
    w(f"- Funding short-skip gun: {len(fund_short or {})}, F&G short-skip: {len(fng_short_20)}")
    w(f"- Pencere: {len(windows)} (3y rolling)")

    REPORT_OUT.write_text("\n".join(out_lines), encoding="utf-8")
    print(f"\nRapor: {REPORT_OUT}")


if __name__ == "__main__":
    main()
