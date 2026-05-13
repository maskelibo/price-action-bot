"""SEC15.4 — Adaptive Risk (Vol-Conditional Dynamic Sizing).

PRE-REGISTERED HIPOTEZ:
  Sabit %4 risk her vol regime'de optimal degil. BTC ATR%>%5 dönemlerde
  defensive (%3), ATR%<%3 sakin dönemlerde agresif (%5-%6) olmali. Bu vol-
  targeting klasigi — dinamik sizing ile DD daha az, getiri korunur veya artar.

V1.5 BASELINE (A6 force-exit + side-cond HIBRIT):
  yıllık +%116.3 / DD -%34.9 / r-adj 3.332 / 13/13 pencere pozitif

GRID (pre-registered, 5 hücre):
  baseline_v1_5      : vol_conditional=False (sabit %4)
  default_3_5        : low=%3, high=%5, low_risk=%5, high_risk=%3 (default)
  agresif_2_5_4      : low=%2.5, high=%4 (geniş range, daha çok değişim)
  konservatif_4_6    : low=%4, high=%6 (dar range, az müdahale)
  symmetric_4_4_5    : low=%4, high=%4, low_risk=%5, high_risk=%5 (sadece extreme normal=%5)

  NOT symmetric_4_4_5: vol-tier yapı içinde "normal" = sabit risk_pct (%4).
  ATR% < 4 -> %5, ATR% > 4 -> %5: yani sürekli %5'e çıkar (sadece normal dilim olmadığı için).
  Hipotez: her gün %5 = uniform overdose, beklenti +ann +DD.

GATES (pre-registered, HARK protection):
  G1 RETURN    mean_ann >= baseline + 3pp           (TRUE edge)
  G2 DD        mean_dd >= baseline - 3pp            (vol-targeting DD GENELLİKLE iyileştirir)
  G3 NEG       0 negatif pencere                    (consistency)
  G4 R-ADJ     r_adj >= baseline + 0.10             (risk-adjusted iyileşme)

POOL: data/_sec13_4_cache/pool_A6_mult15_t30.pkl  (sec13_4 sprint çıktısı)
"""
from __future__ import annotations

import json
import os
import pickle
import sys
import warnings
from pathlib import Path
from statistics import mean, median

os.environ["PA_LOG_QUIET"] = "1"
warnings.filterwarnings("ignore")

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))
sys.path.insert(0, str(ROOT))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from price_action.backtest.lab import (
    ProductionConfig, production_replay, _lazy_build_funding_filters,
)
from price_action.backtest.regime import (
    compute_btc_capitulation_halt,
    compute_btc_atr_pct_calendar,
)
from scripts.v097_balanced_optimization import build_fng_short_skip


POOL_PATH = ROOT / "data" / "_sec13_4_cache" / "pool_A6_mult15_t30.pkl"
REPORT_PATH = ROOT / "reports" / "lab" / "sec15_4_adaptive_risk.md"
JSON_PATH = ROOT / "reports" / "lab" / "sec15_4_adaptive_risk.json"


# =====================================================================
# Walk-forward eval
# =====================================================================

def make_windows(start, end, span_days=3 * 365, step_days=60):
    out = []
    cur = start
    while cur + pd.Timedelta(days=span_days) <= end:
        out.append((cur, cur + pd.Timedelta(days=span_days)))
        cur += pd.Timedelta(days=step_days)
    return out


def evaluate_pool(trades, cfg, windows):
    if not trades:
        return None
    anns, dds = [], []
    for ws, we in windows:
        w = [t for t in trades if ws <= t["entry_ts"] < we]
        r = production_replay(w, cfg)
        if r is None:
            continue
        anns.append(r.annualized(3.0) * 100)
        dds.append(r.max_drawdown * 100)
    if not anns:
        return None
    ma, md = mean(anns), mean(dds)
    ra = ma / abs(md) if md != 0 else 0
    return {
        "mean_ann": ma,
        "median_ann": median(anns),
        "min_ann": min(anns),
        "max_ann": max(anns),
        "mean_dd": md,
        "min_dd": min(dds),
        "r_adj": ra,
        "negatives": sum(1 for a in anns if a < 0),
        "n_windows": len(anns),
    }


# =====================================================================
# MAIN
# =====================================================================

def main():
    print("=" * 110)
    print("SEC15.4 — Adaptive Risk (Vol-Conditional Dynamic Sizing)")
    print("=" * 110)

    # Load A6 force-exit pool (v1.5 stack)
    if not POOL_PATH.exists():
        print(f"FATAL: pool yok: {POOL_PATH}")
        return
    with POOL_PATH.open("rb") as f:
        pool = pickle.load(f)
    pool.sort(key=lambda x: x["entry_ts"])
    print(f"\nPool: {POOL_PATH.name}  n={len(pool)} trade")
    print(f"  range: {pool[0]['entry_ts'].date()} -> {pool[-1]['exit_ts'].date()}")

    # Build BTC ATR% calendar (causal lag1)
    print("\nBTC ATR% calendar build (causal lag1)...")
    btc_atr_cal = compute_btc_atr_pct_calendar(period=14)
    print(f"  n_days={len(btc_atr_cal)}")
    sample_dates = sorted(btc_atr_cal.keys())[:5]
    for d in sample_dates:
        print(f"    {d}  ATR%={btc_atr_cal[d]*100:.2f}%")
    # Distribution stats
    vals = list(btc_atr_cal.values())
    vals_pct = [v * 100 for v in vals]
    vals_pct_sorted = sorted(vals_pct)
    n = len(vals_pct_sorted)
    p25 = vals_pct_sorted[n // 4]
    p50 = vals_pct_sorted[n // 2]
    p75 = vals_pct_sorted[(3 * n) // 4]
    p95 = vals_pct_sorted[(95 * n) // 100]
    n_low = sum(1 for v in vals_pct if v < 3.0)
    n_high = sum(1 for v in vals_pct if v > 5.0)
    print(f"  ATR%% dist: p25={p25:.2f}%  p50={p50:.2f}%  p75={p75:.2f}%  p95={p95:.2f}%")
    print(f"  ATR%<3%: {n_low} gun ({100*n_low/n:.1f}%)  "
          f"ATR%>5%: {n_high} gun ({100*n_high/n:.1f}%)")

    # Build base config (v1.5 stack: BALANCED + side-cond + halt + F&G + funding)
    base = ProductionConfig.from_yaml(str(ROOT / "configs" / "risk_balanced.yaml"))
    halt_cal = compute_btc_capitulation_halt()
    fund_long, fund_short = _lazy_build_funding_filters({
        "funding_filter_enabled": True,
        "funding_aggregation_mode": "00:00_only",
    })
    fng_short_20 = build_fng_short_skip(20)
    combined_short_skip = {**dict(fund_short or {}), **dict(fng_short_20)}

    # v1.5 production stack (A6 + side-cond HIBRIT)
    base_cfg = base.with_overrides(
        alt_data_skip_long=fund_long,
        alt_data_skip_short=combined_short_skip,
        btc_halt_calendar=halt_cal,
        # v1.3 yaml zaten 0.06 / 21
        monthly_dd=0.06,
        monthly_halt_days=21,
        # v1.5 sec14.1 side-cond HIBRIT (long=%10, short=%5)
        monthly_dd_long=0.10,
        monthly_dd_short=0.05,
        # v1.4 sec14.0: max_concurrent=12 yaml'da var
        # Disable confidence_risk_tiers — vol-conditional ile cakismayi engelle.
        # YAML'da tier'lar set edilmis olabilir (BALANCED preset confidence_dynamic).
        # vol-conditional sweep ic tutarlilik icin tier'lari kapat (sabit risk_pct
        # bir lookup olur, vol-conditional override edebilir).
        confidence_risk_tiers=None,
        leverage_tiers=None,
        risk_pct=0.04,  # v1.5 sabit %4
    )
    print(f"\nv1.5 baseline cfg: risk_pct={base_cfg.risk_pct}  "
          f"mdd={base_cfg.monthly_dd}  long_dd={base_cfg.monthly_dd_long}  "
          f"short_dd={base_cfg.monthly_dd_short}")
    print(f"  short_skip days={len(combined_short_skip)}  halt days={sum(halt_cal.values())}")

    # Build windows
    win_start = pool[0]["entry_ts"]
    win_end = pool[-1]["exit_ts"]
    windows = make_windows(win_start, win_end)
    print(f"\nWindows: {len(windows)}  (3y rolling, 60g step)")
    print(f"  first: {windows[0][0].date()} -> {windows[0][1].date()}")
    print(f"  last:  {windows[-1][0].date()} -> {windows[-1][1].date()}")

    # Pre-registered grid (5 cell)
    GRID = [
        ("baseline_v1_5", dict(vol_conditional_risk=False)),
        ("default_3_5",    dict(
            vol_conditional_risk=True,
            vol_low_atr_pct=0.03, vol_high_atr_pct=0.05,
            vol_low_risk_pct=0.05, vol_high_risk_pct=0.03,
            btc_atr_pct_calendar=btc_atr_cal,
        )),
        ("agresif_2_5_4",  dict(
            vol_conditional_risk=True,
            vol_low_atr_pct=0.025, vol_high_atr_pct=0.04,
            vol_low_risk_pct=0.06, vol_high_risk_pct=0.025,  # geniş, agresif uçlar
            btc_atr_pct_calendar=btc_atr_cal,
        )),
        ("konservatif_4_6", dict(
            vol_conditional_risk=True,
            vol_low_atr_pct=0.04, vol_high_atr_pct=0.06,
            vol_low_risk_pct=0.05, vol_high_risk_pct=0.03,  # dar, az müdahale
            btc_atr_pct_calendar=btc_atr_cal,
        )),
        ("symmetric_4_4_5", dict(
            vol_conditional_risk=True,
            vol_low_atr_pct=0.04, vol_high_atr_pct=0.04,
            vol_low_risk_pct=0.05, vol_high_risk_pct=0.05,  # sadece extreme'de "5", normal yok
            btc_atr_pct_calendar=btc_atr_cal,
        )),
    ]

    # Phase 3: Evaluate each cell
    print("\nPhase 3: Walk-forward evaluation\n")
    print(f"{'cell':<22} {'mean_ann':>9} {'med':>7} {'min':>7} {'max':>7} "
          f"{'DD':>7} {'r-adj':>6} {'neg':>4}")
    print("-" * 90)

    results = []
    for label, overrides in GRID:
        cfg = base_cfg.with_overrides(**overrides)
        res = evaluate_pool(pool, cfg, windows)
        if res is None:
            print(f"{label:<22} eval=None")
            continue
        is_baseline = (label == "baseline_v1_5")
        tag = " <-- BASELINE" if is_baseline else ""
        print(f"{label:<22} "
              f"{res['mean_ann']:>+8.2f}% {res['median_ann']:>+6.1f}% "
              f"{res['min_ann']:>+6.1f}% {res['max_ann']:>+6.1f}% "
              f"{res['mean_dd']:>+6.1f}% {res['r_adj']:>5.3f} "
              f"{res['negatives']:>4d}{tag}")
        results.append({
            "cell": label,
            "overrides": {k: v for k, v in overrides.items() if k != "btc_atr_pct_calendar"},
            **res,
            "is_baseline": is_baseline,
        })

    # Phase 4: Gates
    baseline = next((r for r in results if r["is_baseline"]), None)
    if not baseline:
        print("FATAL: baseline missing.")
        return
    b_ann = baseline["mean_ann"]
    b_dd = baseline["mean_dd"]
    b_radj = baseline["r_adj"]
    print(f"\nBASELINE v1.5 measured: ann={b_ann:+.2f}%  DD={b_dd:+.1f}%  "
          f"r-adj={b_radj:.3f}  neg={baseline['negatives']}\n")

    print("# GATES (per cell vs baseline):")
    print(f"  G1 RETURN  mean_ann >= {b_ann + 3.0:.2f}% (baseline +3pp)")
    print(f"  G2 DD      mean_dd >= {b_dd - 3.0:.1f}% (baseline -3pp tolerans)")
    print(f"  G3 NEG     negatives == 0")
    print(f"  G4 R-ADJ   r-adj >= {b_radj + 0.10:.3f} (baseline +0.10)\n")

    print(f"{'cell':<22} {'G1':>4} {'G2':>4} {'G3':>4} {'G4':>4} {'verdict':>8} "
          f"{'d_ann':>9} {'d_dd':>7} {'d_radj':>8}")
    print("-" * 95)
    pass_cells = []
    for r in results:
        if r["is_baseline"]:
            print(f"{r['cell']:<22} {'-':>4} {'-':>4} {'-':>4} {'-':>4} {'BASE':>8} "
                  f"{'-':>9} {'-':>7} {'-':>8}")
            continue
        g1 = r["mean_ann"] >= b_ann + 3.0
        g2 = r["mean_dd"] >= b_dd - 3.0
        g3 = r["negatives"] == 0
        g4 = r["r_adj"] >= b_radj + 0.10
        all_ok = g1 and g2 and g3 and g4
        verdict = "PASS" if all_ok else "fail"
        print(f"{r['cell']:<22} "
              f"{'OK' if g1 else '..':>4} "
              f"{'OK' if g2 else '..':>4} "
              f"{'OK' if g3 else '..':>4} "
              f"{'OK' if g4 else '..':>4} "
              f"{verdict:>8} "
              f"{r['mean_ann']-b_ann:>+8.2f}pp {r['mean_dd']-b_dd:>+6.1f}pp "
              f"{r['r_adj']-b_radj:>+7.3f}")
        if all_ok:
            pass_cells.append(r)

    print()
    winner = None
    if pass_cells:
        pass_cells.sort(key=lambda r: -r["r_adj"])
        winner = pass_cells[0]
        print(f"# WINNER (en yuksek r-adj among PASS):")
        print(f"  cell={winner['cell']}")
        print(f"  ann={winner['mean_ann']:+.2f}%  DD={winner['mean_dd']:+.1f}%  "
              f"r-adj={winner['r_adj']:.3f}")
        print(f"  delta vs baseline: ann {winner['mean_ann']-b_ann:+.2f}pp  "
              f"DD {winner['mean_dd']-b_dd:+.1f}pp  r-adj {winner['r_adj']-b_radj:+.3f}")
    else:
        print("# WINNER: NONE — hicbir hucre tum gate'leri (G1-G4) gecmedi.")
        non_base = [r for r in results if not r["is_baseline"]]
        if non_base:
            non_base.sort(key=lambda r: -r["r_adj"])
            top = non_base[0]
            print(f"  EN YUKSEK r-adj (PASS-DISI): {top['cell']} "
                  f"r-adj={top['r_adj']:.3f} ann={top['mean_ann']:+.2f}% "
                  f"DD={top['mean_dd']:+.1f}%")

    # Persist
    JSON_PATH.parent.mkdir(parents=True, exist_ok=True)
    with JSON_PATH.open("w", encoding="utf-8") as f:
        json.dump({
            "baseline": baseline,
            "results": results,
            "winner": winner,
            "n_windows": len(windows),
            "config": {
                "preset": "BALANCED+F&G+funding+halt+v1.5(side-cond+A6)",
                "monthly_dd": base_cfg.monthly_dd,
                "monthly_dd_long": base_cfg.monthly_dd_long,
                "monthly_dd_short": base_cfg.monthly_dd_short,
                "halt_days": base_cfg.monthly_halt_days,
                "risk_pct_default": base_cfg.risk_pct,
            },
            "btc_atr_pct_dist": {
                "n_days": n,
                "p25_pct": p25, "p50_pct": p50, "p75_pct": p75, "p95_pct": p95,
                "low_pct_share": 100 * n_low / n,
                "high_pct_share": 100 * n_high / n,
            },
        }, f, indent=2, default=str)
    print(f"\nJSON saved: {JSON_PATH}")

    # Markdown report
    write_report(REPORT_PATH, results, baseline, winner, b_ann, b_dd, b_radj,
                 len(windows), len(pool), n_low, n_high, n, p25, p50, p75, p95)
    print(f"MD saved:   {REPORT_PATH}")

    return results, winner


def write_report(path, results, baseline, winner, b_ann, b_dd, b_radj, n_windows,
                 n_trades, n_low, n_high, n_days, p25, p50, p75, p95):
    L = []
    L.append("# SEC15.4 — Adaptive Risk (Vol-Conditional Dynamic Sizing)\n\n")
    L.append("**Tarih:** 2026-05-13  \n")
    L.append("**Sprint:** sec15_4_adaptive_risk  \n")
    L.append(f"**Walk-forward:** {n_windows} pencere (3y rolling, 60g step)  \n")
    L.append("**Pool:** v1.5 (A6 force-exit, time=30bar, mult=1.5)  ")
    L.append(f"n_trades={n_trades}\n")
    L.append("**Stack:** BALANCED + halt + F&G + funding + side-cond HIBRIT  \n\n")

    L.append("## Hipotez\n\n")
    L.append("Sabit %4 risk her vol regime'de optimal degil. BTC ATR% bucket'ina "
             "gore dinamik risk_pct -> oynak donemlerde defensive (kucuk poz), "
             "sakin donemlerde agresif (buyuk poz). Vol-targeting klasigi: "
             "DD genelde dusurur, getiri korunur veya artar.\n\n")
    L.append(f"BTC ATR%% dist (causal lag1, n={n_days} gun): "
             f"p25={p25:.2f}%, p50={p50:.2f}%, p75={p75:.2f}%, p95={p95:.2f}%. "
             f"ATR%<3% gun sayisi: {n_low} ({100*n_low/n_days:.1f}%), "
             f"ATR%>5%: {n_high} ({100*n_high/n_days:.1f}%).\n\n")

    L.append("## Pre-registered Grid (5 hücre)\n\n")
    L.append("| cell | low_atr% | high_atr% | low_risk% | high_risk% | normal_risk% |\n")
    L.append("|------|----------|-----------|-----------|------------|--------------|\n")
    for r in results:
        ov = r["overrides"]
        if not ov.get("vol_conditional_risk", False):
            L.append(f"| {r['cell']} | — | — | — | — | 4.0 (sabit) |\n")
        else:
            L.append(f"| {r['cell']} | {ov['vol_low_atr_pct']*100:.1f} | "
                     f"{ov['vol_high_atr_pct']*100:.1f} | "
                     f"{ov['vol_low_risk_pct']*100:.1f} | "
                     f"{ov['vol_high_risk_pct']*100:.1f} | 4.0 |\n")
    L.append("\n")

    L.append(f"## Sonuclar ({n_windows} pencere walk-forward)\n\n")
    L.append("| cell | mean_ann | median | min | max | mean_DD | r-adj | neg |\n")
    L.append("|------|----------|--------|-----|-----|---------|-------|-----|\n")
    for r in results:
        tag = " (baseline)" if r["is_baseline"] else ""
        L.append(f"| {r['cell']}{tag} | "
                 f"{r['mean_ann']:+.2f}% | {r['median_ann']:+.1f}% | "
                 f"{r['min_ann']:+.1f}% | {r['max_ann']:+.1f}% | "
                 f"{r['mean_dd']:+.1f}% | {r['r_adj']:.3f} | "
                 f"{r['negatives']}/{r['n_windows']} |\n")
    L.append("\n")

    L.append("## Statistical Gates\n\n")
    L.append(f"- **G1 RETURN**  mean_ann >= {b_ann + 3.0:.2f}%  (baseline {b_ann:+.2f}% +3pp)\n")
    L.append(f"- **G2 DD**      mean_dd >= {b_dd - 3.0:.1f}%  (baseline {b_dd:+.1f}% -3pp tolerans)\n")
    L.append(f"- **G3 NEG**     negatives == 0\n")
    L.append(f"- **G4 R-ADJ**   r_adj >= {b_radj + 0.10:.3f}  (baseline {b_radj:.3f} +0.10)\n\n")

    L.append("## Gate Verdict\n\n")
    L.append("| cell | G1 | G2 | G3 | G4 | verdict | d_ann | d_dd | d_radj |\n")
    L.append("|------|----|----|----|----|---------|-------|------|--------|\n")
    for r in results:
        if r["is_baseline"]:
            L.append(f"| {r['cell']} | — | — | — | — | BASE | — | — | — |\n")
            continue
        g1 = r["mean_ann"] >= b_ann + 3.0
        g2 = r["mean_dd"] >= b_dd - 3.0
        g3 = r["negatives"] == 0
        g4 = r["r_adj"] >= b_radj + 0.10
        ok = g1 and g2 and g3 and g4
        L.append(f"| {r['cell']} | "
                 f"{'OK' if g1 else '..'} | "
                 f"{'OK' if g2 else '..'} | "
                 f"{'OK' if g3 else '..'} | "
                 f"{'OK' if g4 else '..'} | "
                 f"{'**PASS**' if ok else 'fail'} | "
                 f"{r['mean_ann']-b_ann:+.2f}pp | {r['mean_dd']-b_dd:+.1f}pp | "
                 f"{r['r_adj']-b_radj:+.3f} |\n")
    L.append("\n")

    L.append("## Karar\n\n")
    if winner is not None:
        L.append(f"**WINNER:** `{winner['cell']}`  \n")
        ov = winner["overrides"]
        L.append(f"- low_atr%={ov['vol_low_atr_pct']*100:.1f}, "
                 f"high_atr%={ov['vol_high_atr_pct']*100:.1f}  \n")
        L.append(f"- low_risk%={ov['vol_low_risk_pct']*100:.1f}, "
                 f"high_risk%={ov['vol_high_risk_pct']*100:.1f}, normal=4.0%  \n")
        L.append(f"- yillik {winner['mean_ann']:+.2f}% "
                 f"(baseline {b_ann:+.2f}%, +{winner['mean_ann']-b_ann:.2f}pp)\n")
        L.append(f"- DD {winner['mean_dd']:+.1f}% "
                 f"(baseline {b_dd:+.1f}%, {winner['mean_dd']-b_dd:+.1f}pp)\n")
        L.append(f"- r-adj {winner['r_adj']:.3f} "
                 f"(baseline {b_radj:.3f}, +{winner['r_adj']-b_radj:.3f})\n")
        L.append(f"- {winner['n_windows']}/{n_windows} pencere pozitif: "
                 f"{'EVET' if winner['negatives'] == 0 else 'HAYIR'}\n\n")
        L.append("**ONERI:** risk_balanced.yaml'a `vol_conditional_risk` block ekle, "
                 "production'a v1.6 olarak promote et.\n")
    else:
        L.append("**RED — hicbir hucre tum gate'leri (G1-G4) gecmedi.**\n\n")
        non_base = [r for r in results if not r["is_baseline"]]
        if non_base:
            non_base.sort(key=lambda r: -r["r_adj"])
            top = non_base[0]
            L.append(f"En yuksek r-adj non-PASS aday: `{top['cell']}` "
                     f"(r-adj {top['r_adj']:.3f}, ann {top['mean_ann']:+.2f}%, "
                     f"DD {top['mean_dd']:+.1f}%).\n\n")
        L.append("Yorum gerekirse: vol-targeting BTC ATR%-bucket bazli rejim "
                 "ayriminin trade-pool R-distribution'unda anlamli edge uretmedigini "
                 "gosterir. Olasi sebepler:\n"
                 "- Halt + F&G + funding zaten yuksek-vol gunlerini filterliyor "
                 "(double-counting).\n"
                 "- Side-cond monthly_dd zaten dinamik dur durdur (DD-self-limiting).\n"
                 "- ATR%<3 sakin gun sayisi az -> agresif uplift kucuk pencerelerde.\n"
                 "- Trade dagilimi vol-bucket icinde EDGE FARKLI degil (R~ATR%).\n\n"
                 "Bu durumda **production v1.5 (sabit %4) korunmali**, "
                 "lab.py'a vol_conditional_risk hooks eklendi ama default DEGISTIRILMIYOR.\n")
    L.append("\n## Pre-Reg Disipline & Reproducibility\n\n")
    L.append("- Grid pre-registered (5 hucre, default + 3 sweep + 1 symmetric kontrol).\n")
    L.append("- HARK protection: gates onceden yazildi, post-hoc gate-tweak yok.\n")
    L.append("- BTC ATR% calendar CAUSAL: T gunu trade T-1 close-of-day verisini bilir "
             "(`atr_pct.shift(1)`), lookahead-bias yok.\n")
    L.append(f"- Pool cache: `data/_sec13_4_cache/pool_A6_mult15_t30.pkl` ({n_trades} trade).\n")
    L.append(f"- JSON: `reports/lab/sec15_4_adaptive_risk.json`\n")
    L.append("- Re-run: `PYTHONPATH=src python scripts/sec15_4_adaptive_risk.py`\n")
    L.append("- API: `ProductionConfig(vol_conditional_risk=True, "
             "btc_atr_pct_calendar=calendar, vol_low_atr_pct=0.03, ...)`\n")
    with open(path, "w", encoding="utf-8") as f:
        f.writelines(L)


if __name__ == "__main__":
    main()
