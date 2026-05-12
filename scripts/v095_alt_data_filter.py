"""v0.9.5 — ALT-DATA filter sweep.

3 filter aile:
  A) Funding rate: extreme positive (>X) -> long skip (overheated)
  B) Fear & Greed: extreme greed (>80) -> long skip; extreme fear (<20) -> short skip
  C) Combo: en guclusu + balanced preset

Test:
  - 3y rolling 13 pencere
  - BASELINE vs filter-on
  - WORST/BEST pencere ozel

Output:
  reports/v095_alt_data_results.txt
"""
from __future__ import annotations

import os
import sys
from datetime import date, timedelta
from pathlib import Path
from statistics import mean, median

os.environ["PA_LOG_QUIET"] = "1"

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from price_action.backtest.lab import ProductionConfig, production_replay
from scripts.v09_optimize_top10 import _gather, TOP_10

ALT = ROOT / "data" / "alt_data"
REP = ROOT / "reports" / "v095_alt_data_results.txt"


# ---------------------------------------------------------------------------
# Veri yukleyiciler
# ---------------------------------------------------------------------------


def load_funding_daily() -> pd.DataFrame:
    """8h funding -> daily avg/sum. Returns DataFrame(date, daily_avg, daily_sum)."""
    p = ALT / "funding_BTCUSDT.csv"
    df = pd.read_csv(p)
    df["ts"] = pd.to_datetime(df["ts"], utc=True, format="ISO8601")
    df["date"] = df["ts"].dt.date
    g = df.groupby("date").agg(
        daily_avg=("fundingRate", "mean"),
        daily_sum=("fundingRate", "sum"),
        n_funds=("fundingRate", "count"),
    ).reset_index()
    return g


def load_fng_daily() -> pd.DataFrame:
    """F&G CSV. Returns DataFrame(date, value, classification)."""
    p = ALT / "fng_daily.csv"
    df = pd.read_csv(p)
    df["ts"] = pd.to_datetime(df["ts"], utc=True, format="ISO8601")
    df["date"] = pd.to_datetime(df["date"]).dt.date
    return df[["date", "value", "classification"]]


# ---------------------------------------------------------------------------
# Filter calendarlari (date -> bool)
# ---------------------------------------------------------------------------


def build_funding_long_skip(funding_df: pd.DataFrame, thr: float = 0.0001) -> dict:
    """Funding daily_avg > thr olan gunlerde long skip.

    Binance 8h funding "normal" = +%0.01 (0.0001). Yuksek = >+%0.02 (0.0002).
    daily_avg sistemde 3 ortalama -> threshold biraz dusurulebilir.
    """
    cal = {}
    for _, r in funding_df.iterrows():
        if pd.isna(r["daily_avg"]):
            continue
        if r["daily_avg"] > thr:
            cal[r["date"]] = True
    return cal


def build_funding_short_skip(funding_df: pd.DataFrame, thr: float = -0.0001) -> dict:
    """Funding daily_avg < thr (extreme negative) -> short skip (overshort squeeze setup)."""
    cal = {}
    for _, r in funding_df.iterrows():
        if pd.isna(r["daily_avg"]):
            continue
        if r["daily_avg"] < thr:
            cal[r["date"]] = True
    return cal


def build_fng_long_skip(fng_df: pd.DataFrame, thr: int = 80) -> dict:
    """F&G > thr (extreme greed) -> long skip. Contrarian sentiment filter."""
    cal = {}
    for _, r in fng_df.iterrows():
        if pd.isna(r["value"]):
            continue
        if int(r["value"]) >= thr:
            cal[r["date"]] = True
    return cal


def build_fng_short_skip(fng_df: pd.DataFrame, thr: int = 20) -> dict:
    """F&G < thr (extreme fear) -> short skip. Contrarian sentiment filter."""
    cal = {}
    for _, r in fng_df.iterrows():
        if pd.isna(r["value"]):
            continue
        if int(r["value"]) <= thr:
            cal[r["date"]] = True
    return cal


def build_fng_skip_all_extremes(fng_df: pd.DataFrame, low: int = 20, high: int = 80) -> dict:
    """F&G <low veya >high -> tum trade skip (extreme regime kacis)."""
    cal = {}
    for _, r in fng_df.iterrows():
        v = r["value"]
        if pd.isna(v):
            continue
        v = int(v)
        if v <= low or v >= high:
            cal[r["date"]] = True
    return cal


# ---------------------------------------------------------------------------
# Backtest harness — 3y rolling 13 pencere
# ---------------------------------------------------------------------------


def _gather_all_trades() -> list[dict]:
    print("Trade'leri topluyor (10 strat x 11 sym)...")
    all_trades = []
    for m, c in TOP_10:
        trs = _gather(m, c)
        all_trades.extend(trs)
    all_trades.sort(key=lambda x: x["entry_ts"])
    print(f"  Toplam: {len(all_trades)}")
    return all_trades


def _build_windows(all_trades, span_days=3 * 365, step_days=60):
    start = all_trades[0]["entry_ts"]
    end = all_trades[-1]["exit_ts"]
    windows = []
    cur = start
    while cur + pd.Timedelta(days=span_days) <= end:
        windows.append((cur, cur + pd.Timedelta(days=span_days)))
        cur += pd.Timedelta(days=step_days)
    return windows


def run_scenario(name: str, all_trades, windows, cfg, out_lines):
    anns, dds, ns, wrs = [], [], [], []
    per_window = []
    for ws, we in windows:
        w = [t for t in all_trades if ws <= t["entry_ts"] < we]
        r = production_replay(w, cfg)
        if r is None:
            continue
        ann = r.annualized(3.0) * 100
        dd = r.max_drawdown * 100
        anns.append(ann)
        dds.append(dd)
        ns.append(r.trades)
        wrs.append(r.win_rate * 100)
        per_window.append((ws.date(), we.date(), r.trades, ann, dd, r.win_rate * 100))
    if not anns:
        out_lines.append(f"  {name}: NO RESULTS")
        return None
    ma, mdd, mwr = mean(anns), mean(dds), mean(wrs)
    ra = ma / abs(mdd) if mdd != 0 else 0
    line = (
        f"  {name:<58} | ann {ma:>+6.2f}% (min {min(anns):>+5.1f} med {median(anns):>+5.1f} max {max(anns):>+5.1f}) | "
        f"DD {mdd:>+5.0f}% (worst {min(dds):>+4.0f}) | WR {mwr:>4.1f}% | r-adj {ra:>5.2f} | n={int(mean(ns))}"
    )
    print(line)
    out_lines.append(line)
    return {
        "name": name,
        "ann_mean": ma, "ann_min": min(anns), "ann_max": max(anns), "ann_med": median(anns),
        "dd_mean": mdd, "dd_worst": min(dds),
        "wr_mean": mwr, "r_adj": ra, "n_mean": mean(ns),
        "per_window": per_window,
    }


# ---------------------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------------------


def main():
    lines = []
    p = lambda s: (print(s), lines.append(s))
    p("=" * 110)
    p("v0.9.5 ALT-DATA FILTER TEST — 3y rolling 13 pencere")
    p("=" * 110)

    # Veri kalite raporu
    p("\n[VERI ENVANTERI]")
    funding_df = load_funding_daily()
    fng_df = load_fng_daily()
    p(f"  funding_BTCUSDT.csv: {len(funding_df)} daily aggregations  "
      f"({funding_df['date'].min()} -> {funding_df['date'].max()})")
    p(f"    daily_avg mean={funding_df['daily_avg'].mean():.6f}  std={funding_df['daily_avg'].std():.6f}  "
      f"min={funding_df['daily_avg'].min():.6f}  max={funding_df['daily_avg'].max():.6f}")
    p(f"    p95={funding_df['daily_avg'].quantile(0.95):.6f}  p05={funding_df['daily_avg'].quantile(0.05):.6f}")
    p(f"  fng_daily.csv:       {len(fng_df)} days  "
      f"({fng_df['date'].min()} -> {fng_df['date'].max()})")
    p(f"    value mean={fng_df['value'].mean():.1f}  std={fng_df['value'].std():.1f}  "
      f"days >=80: {(fng_df['value']>=80).sum()}  days <=20: {(fng_df['value']<=20).sum()}")
    p("  OI: 1y endpoint hit Binance limit, atlandi (funding+F&G yeterli ilk pass)")

    all_trades = _gather_all_trades()
    windows = _build_windows(all_trades)
    p(f"\n  Pencere sayisi: {len(windows)} (3y, 60-gun adim)")
    p(f"  Trade tarih araligi: {all_trades[0]['entry_ts'].date()} -> {all_trades[-1]['exit_ts'].date()}")

    # Tarihsel olarak signal sayilarini hesapla
    p("\n[FILTER GUN SAYILARI — tarihsel coverage]")
    cal_f_long = build_funding_long_skip(funding_df, thr=0.0001)
    cal_f_long_strict = build_funding_long_skip(funding_df, thr=0.00015)
    cal_f_short = build_funding_short_skip(funding_df, thr=-0.0001)
    cal_fng_long = build_fng_long_skip(fng_df, thr=80)
    cal_fng_long_strict = build_fng_long_skip(fng_df, thr=75)
    cal_fng_short = build_fng_short_skip(fng_df, thr=20)
    cal_fng_short_strict = build_fng_short_skip(fng_df, thr=25)
    cal_fng_extreme = build_fng_skip_all_extremes(fng_df, low=15, high=85)
    p(f"  funding daily_avg > +0.0001 (mild overheat): {len(cal_f_long)} gun")
    p(f"  funding daily_avg > +0.00015 (strict):       {len(cal_f_long_strict)} gun")
    p(f"  funding daily_avg < -0.0001 (overshort):     {len(cal_f_short)} gun")
    p(f"  F&G >= 80 (extreme greed):                    {len(cal_fng_long)} gun")
    p(f"  F&G >= 75 (greed):                            {len(cal_fng_long_strict)} gun")
    p(f"  F&G <= 20 (extreme fear):                     {len(cal_fng_short)} gun")
    p(f"  F&G <= 25 (fear):                             {len(cal_fng_short_strict)} gun")
    p(f"  F&G extreme (<=15 or >=85):                   {len(cal_fng_extreme)} gun")

    # Senaryolar
    base_prod = ProductionConfig.from_yaml().with_overrides(concentration_max_per_symbol_pct=0.20)
    base_aggr = ProductionConfig.from_yaml("configs/risk_aggressive.yaml")
    base_balanced = ProductionConfig.from_yaml("configs/risk_balanced.yaml")

    p("\n" + "=" * 110)
    p("BASELINE")
    p("=" * 110)
    p(f"  {'scenario':<58} | {'annual':>14}  ...                       | {'DD':>5}            | {'WR':>5}  | r-adj | n")
    results = {}
    results["baseline_prod"] = run_scenario(
        "BASELINE v0.9.2 production (conc 0.20)", all_trades, windows, base_prod, lines)
    results["baseline_aggr"] = run_scenario(
        "BASELINE v0.9.3 AGGRESSIVE (r%4)", all_trades, windows, base_aggr, lines)
    results["baseline_balanced"] = run_scenario(
        "BASELINE v0.9.4 BALANCED (halt+r%4)", all_trades, windows, base_balanced, lines)

    p("\n" + "=" * 110)
    p("FILTER FAMILY A — FUNDING RATE")
    p("=" * 110)
    p("Hipotez: extreme pos funding -> long skip (overlong squeeze risk); ")
    p("         extreme neg funding -> short skip (overshort squeeze risk).")
    p("")
    # Baseline-prod with funding filters
    results["fund_long_mild"] = run_scenario(
        "PROD + funding>0.0001 long-skip", all_trades, windows,
        base_prod.with_overrides(alt_data_skip_long=cal_f_long), lines)
    results["fund_long_strict"] = run_scenario(
        "PROD + funding>0.00015 long-skip (strict)", all_trades, windows,
        base_prod.with_overrides(alt_data_skip_long=cal_f_long_strict), lines)
    results["fund_short_mild"] = run_scenario(
        "PROD + funding<-0.0001 short-skip", all_trades, windows,
        base_prod.with_overrides(alt_data_skip_short=cal_f_short), lines)
    results["fund_both"] = run_scenario(
        "PROD + funding both-side filter (mild)", all_trades, windows,
        base_prod.with_overrides(alt_data_skip_long=cal_f_long, alt_data_skip_short=cal_f_short), lines)

    p("\n" + "=" * 110)
    p("FILTER FAMILY B — FEAR & GREED")
    p("=" * 110)
    p("Hipotez: F&G>=80 (extreme greed) -> long skip;")
    p("         F&G<=20 (extreme fear) -> short skip (contrarian sentiment)")
    p("")
    results["fng_long_80"] = run_scenario(
        "PROD + F&G>=80 long-skip (extreme greed)", all_trades, windows,
        base_prod.with_overrides(alt_data_skip_long=cal_fng_long), lines)
    results["fng_long_75"] = run_scenario(
        "PROD + F&G>=75 long-skip (greed)", all_trades, windows,
        base_prod.with_overrides(alt_data_skip_long=cal_fng_long_strict), lines)
    results["fng_short_20"] = run_scenario(
        "PROD + F&G<=20 short-skip (extreme fear)", all_trades, windows,
        base_prod.with_overrides(alt_data_skip_short=cal_fng_short), lines)
    results["fng_short_25"] = run_scenario(
        "PROD + F&G<=25 short-skip (fear)", all_trades, windows,
        base_prod.with_overrides(alt_data_skip_short=cal_fng_short_strict), lines)
    results["fng_both_extreme"] = run_scenario(
        "PROD + F&G both-side contrarian (80/20)", all_trades, windows,
        base_prod.with_overrides(alt_data_skip_long=cal_fng_long, alt_data_skip_short=cal_fng_short), lines)
    results["fng_both_75_25"] = run_scenario(
        "PROD + F&G both-side contrarian (75/25)", all_trades, windows,
        base_prod.with_overrides(alt_data_skip_long=cal_fng_long_strict, alt_data_skip_short=cal_fng_short_strict), lines)
    results["fng_skip_extremes"] = run_scenario(
        "PROD + F&G skip both-extremes (<=15 or >=85)", all_trades, windows,
        base_prod.with_overrides(alt_data_skip_all=cal_fng_extreme), lines)

    p("\n" + "=" * 110)
    p("FILTER FAMILY C — COMBO + BALANCED PRESET")
    p("=" * 110)
    p("En guclusu (asagidaki ranking'e bakacaz) BALANCED ile kombine + AGGRESSIVE ile kombine")
    p("")
    results["fng75_25_balanced"] = run_scenario(
        "BALANCED + F&G 75/25 contrarian", all_trades, windows,
        base_balanced.with_overrides(alt_data_skip_long=cal_fng_long_strict, alt_data_skip_short=cal_fng_short_strict), lines)
    results["fng75_25_aggr"] = run_scenario(
        "AGGRESSIVE + F&G 75/25 contrarian", all_trades, windows,
        base_aggr.with_overrides(alt_data_skip_long=cal_fng_long_strict, alt_data_skip_short=cal_fng_short_strict), lines)
    results["fund_mild_aggr"] = run_scenario(
        "AGGRESSIVE + funding>0.0001 long-skip", all_trades, windows,
        base_aggr.with_overrides(alt_data_skip_long=cal_f_long), lines)
    results["fund_both_aggr"] = run_scenario(
        "AGGRESSIVE + funding both-side filter", all_trades, windows,
        base_aggr.with_overrides(alt_data_skip_long=cal_f_long, alt_data_skip_short=cal_f_short), lines)
    results["combo_all_prod"] = run_scenario(
        "PROD + F&G 75/25 + funding both", all_trades, windows,
        base_prod.with_overrides(
            alt_data_skip_long={**cal_fng_long_strict, **cal_f_long},
            alt_data_skip_short={**cal_fng_short_strict, **cal_f_short}), lines)
    results["combo_all_balanced"] = run_scenario(
        "BALANCED + F&G 75/25 + funding both", all_trades, windows,
        base_balanced.with_overrides(
            alt_data_skip_long={**cal_fng_long_strict, **cal_f_long},
            alt_data_skip_short={**cal_fng_short_strict, **cal_f_short}), lines)

    # ============================================================
    # RANKING
    # ============================================================
    p("\n" + "=" * 110)
    p("RANKING — r-adj (yillik / |DD|)")
    p("=" * 110)
    valid = [v for v in results.values() if v is not None]
    valid.sort(key=lambda x: -x["r_adj"])
    p(f"  {'#':>2}  {'scenario':<58}  yillik    DD     r-adj  WR")
    for i, v in enumerate(valid[:12], 1):
        p(f"  {i:>2}. {v['name']:<58}  {v['ann_mean']:>+6.2f}%  {v['dd_mean']:>+5.0f}%  {v['r_adj']:>5.2f}  {v['wr_mean']:>5.1f}%")

    p("\nRANKING — annual mean")
    valid_by_ann = sorted(valid, key=lambda x: -x["ann_mean"])
    for i, v in enumerate(valid_by_ann[:12], 1):
        p(f"  {i:>2}. {v['name']:<58}  {v['ann_mean']:>+6.2f}%  {v['dd_mean']:>+5.0f}%  {v['r_adj']:>5.2f}  {v['wr_mean']:>5.1f}%")

    p("\nRANKING — annual MIN (worst window — daha az kotu = daha tutarli)")
    valid_by_min = sorted(valid, key=lambda x: -x["ann_min"])
    for i, v in enumerate(valid_by_min[:10], 1):
        p(f"  {i:>2}. {v['name']:<58}  ann_min {v['ann_min']:>+6.1f}%  ann_med {v['ann_med']:>+5.1f}%  DD_worst {v['dd_worst']:>+5.0f}%")

    # ============================================================
    # WORST/BEST window comparison
    # ============================================================
    p("\n" + "=" * 110)
    p("WORST/BEST PENCERE — baseline vs en iyi filter")
    p("=" * 110)
    if results.get("baseline_prod") and valid:
        b = results["baseline_prod"]
        bw_b = min(b["per_window"], key=lambda x: x[3])
        bb_b = max(b["per_window"], key=lambda x: x[3])
        p(f"\n  BASELINE production:")
        p(f"    worst: {bw_b[0]} -> {bw_b[1]} | ann {bw_b[3]:+.1f}% | DD {bw_b[4]:+.0f}% | WR {bw_b[5]:.1f}% | n={bw_b[2]}")
        p(f"    best:  {bb_b[0]} -> {bb_b[1]} | ann {bb_b[3]:+.1f}% | DD {bb_b[4]:+.0f}% | WR {bb_b[5]:.1f}% | n={bb_b[2]}")
        # En iyi r-adj filter karsilastir
        top = valid[0]
        if top["name"] != results["baseline_prod"]["name"]:
            bw_t = min(top["per_window"], key=lambda x: x[3])
            bb_t = max(top["per_window"], key=lambda x: x[3])
            p(f"\n  BEST FILTER ({top['name']}):")
            p(f"    worst: {bw_t[0]} -> {bw_t[1]} | ann {bw_t[3]:+.1f}% | DD {bw_t[4]:+.0f}% | WR {bw_t[5]:.1f}% | n={bw_t[2]}")
            p(f"    best:  {bb_t[0]} -> {bb_t[1]} | ann {bb_t[3]:+.1f}% | DD {bb_t[4]:+.0f}% | WR {bb_t[5]:.1f}% | n={bb_t[2]}")
            p(f"\n  WORST-WINDOW UPLIFT (filter - baseline) = {top['ann_min'] - b['ann_min']:+.2f}pp")
            p(f"  AVG-ANNUAL DELTA                       = {top['ann_mean'] - b['ann_mean']:+.2f}pp")
            p(f"  AVG-DD DELTA (filter - baseline)       = {top['dd_mean'] - b['dd_mean']:+.2f}pp")

    # Write to report
    REP.parent.mkdir(parents=True, exist_ok=True)
    REP.write_text("\n".join(lines), encoding="utf-8")
    p(f"\nRapor yazildi -> {REP}")


if __name__ == "__main__":
    main()
