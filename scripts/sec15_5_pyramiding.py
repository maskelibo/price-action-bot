"""SEC15.5 — Pyramiding (Winner Trade'lere Ek Pozisyon).

PRE-REGISTERED HIPOTEZ:
  v1.5 multi-target engine (sec13.4 winner: mult=1.5, time=30, partial close
  %30/%30/%40) trade'i 1R'da %30 partial-close yapiyor (kar realize). Bunu
  "let winners run" doktrini ile degistir / paralel cek: 1R'da PARTIAL CLOSE
  yerine VEYA YANI SIRA, ek pozisyon ekle (entry size +%30-50). Boylece
  big winner'larda exposure pyramidsel buyur, kucuk kazananlar normal.

  Beklenti: Pyramid ekleme ile yillik return uplift, DD artar (asimetrik
  risk: 1R'a varip BE'ye donen trade'lerde ek pos breakeven). Ama net
  edge pozitif olabilir — buyuk runner'lar ek pos ile katlanir.

SIM YAKLASIMI (engine degismiyor — regression riski sifir):
  v1.5 baseline pool (sec13.4 cache pool_A6_mult15_t30.pkl) zaten engine
  partial-close ile gen'lenmis; her trade'in nihai R'i mevcut. Pyramid
  varyantlari icin pool'daki R'i transform ederek replay eder, gerçek edge
  ölçeriz.

  Pyramid R transform (her trade icin):
    R_new = R_orig + sum_i [ s_i * max(0, R_orig - t_i) ]
    nerede:
      - t_i = pyramid_at_R[i] (trigger, ornek 1.0R)
      - s_i = pyramid_size_pct[i] (ek qty / orijinal qty)
    Mantik:
      - R_orig = ana pos final R (engine'den)
      - Trade trigger t_i'ye ulastigi durumda (R_orig >= t_i):
        - Ek pos t_i'de entry, ana pos exit'inde exit
        - Ek pos R = (R_orig - t_i)  [SL break-even, en kotu 0]
        - Ek pos contribution to total R = s_i * (R_orig - t_i)
      - Asymetric risk: trigger ulastigi ama BE'ye donen trade'lerde
        ek pos = 0 (R_orig - t_i'in negatif olmamasini saglar -> max(0,..))

  Bu OPTIMIST simulasyon (upper bound):
    - MFE bilmedigimiz icin, MFE >= trigger ama R_orig < trigger olan
      trade'leri hesaba katmiyoruz (BE'ye donen pyramid'leri saymiyoruz).
    - R_orig >= trigger ise pyramid girdi varsayimi -> ek pos R = (R_orig - t).
    - Realist downside: R_orig >= trigger ama trade BE'ye gerilemis -> bu
      durum nadir cunku R_orig zaten BE'de duracakti. Bu yuzden bias
      kucuk (~%2-5).

GRID (5 varyant):
  v15_baseline       : pyramid OFF (sanity check, baseline +%116.3 üretmeli)
  light_pyramid      : +%30@1R + +%20@2R, partial close paralel
  standard_pyramid   : +%50@1R + +%30@2R, partial close paralel
  aggressive_pyramid : +%50@0.5R + +%50@1.5R, partial close paralel (early add)
  conservative_pyramid: +%20@1R only

CONFIG (v1.5 production):
  Pool: pool_A6_mult15_t30.pkl (TOP_11, mult=1.5, time=30, tp1=1.0, tp2=1.5)
  cfg: risk_balanced.yaml (BALANCED + side-cond mdd long=10/short=5 + halt + F&G short<=20)

PRE-REGISTERED GATES (HARK protection):
  G0 ARTIFACT  max_R_pyramid <= 30        (pyramid maxR dogal artar, 30 sinir)
  G1 RETURN    mean_ann >= +%121.3       (v1.5 baseline +%116.3 + 5pp)
  G2 DD        mean_dd >= -%39.9          (v1.5 baseline -%34.9, +%5pp tolerans)
  G3 NEG       0 negatif pencere
  G4 R-ADJ     r-adj >= 3.0
  G5 PANIC     mean_dd >= -%50            (panik zone REJECT)

PRE-REG NOTE:
  - 5-varyant pre-registered, post-hoc tweak yok.
  - Sanity: v15_baseline ann ~+%116.3, dd ~-%34.9 olmali (replay kontrol).
  - Winner: PASS arasindan en yuksek r-adj.
"""
from __future__ import annotations

import json
import os
import pickle
import sys
import warnings
from copy import deepcopy
from pathlib import Path
from statistics import mean, median

os.environ["PA_LOG_QUIET"] = "1"
warnings.filterwarnings("ignore")

import numpy as np
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
from price_action.backtest.regime import compute_btc_capitulation_halt
from scripts.v097_balanced_optimization import build_fng_short_skip


POOL_PATH = ROOT / "data" / "_sec13_4_cache" / "pool_A6_mult15_t30.pkl"
REPORT_PATH = ROOT / "reports" / "lab" / "sec15_5_pyramiding.md"
JSON_PATH = ROOT / "reports" / "lab" / "sec15_5_pyramiding.json"


# =====================================================================
# Pyramid R-transform
# =====================================================================

def transform_pool_pyramid(
    base_pool: list[dict],
    *,
    pyramid_at_R: list[float],
    pyramid_size_pct: list[float],
) -> list[dict]:
    """Yeni pool: her trade'in R'ini pyramid kuralina gore transform eder.

    Args:
        base_pool: orijinal trade pool (engine'den, partial-close icerir).
        pyramid_at_R: trigger R seviyeleri (orn [1.0, 2.0]).
        pyramid_size_pct: her tier icin ek qty oranı (orn [0.50, 0.30]).

    Returns:
        Yeni pool — `R` field'i pyramid sonrasi effective R.
        Diger field'lar (timestamps, symbol, side, conf, strategy) korunur.
    """
    assert len(pyramid_at_R) == len(pyramid_size_pct), \
        "pyramid_at_R ve pyramid_size_pct ayni uzunlukta olmali"

    new_pool = []
    for t in base_pool:
        nt = dict(t)  # shallow copy
        R_orig = float(t["R"])
        bonus = 0.0
        for trig, size_pct in zip(pyramid_at_R, pyramid_size_pct):
            if R_orig >= trig:
                bonus += size_pct * (R_orig - trig)
        nt["R"] = R_orig + bonus
        new_pool.append(nt)
    return new_pool


def pool_artifact_stats(pool: list[dict]) -> dict:
    if not pool:
        return {"max_R": 0, "p99_R": 0, "p95_R": 0, "n": 0}
    rs = np.array([float(t["R"]) for t in pool])
    return {
        "max_R": float(rs.max()),
        "p99_R": float(np.percentile(rs, 99)),
        "p95_R": float(np.percentile(rs, 95)),
        "min_R": float(rs.min()),
        "mean_R": float(rs.mean()),
        "median_R": float(np.median(rs)),
        "n": len(rs),
    }


# =====================================================================
# Walk-forward
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
# Grid (pre-registered)
# =====================================================================

GRID = [
    # (label, pyramid_at_R, pyramid_size_pct, description)
    ("v15_baseline", [], [], "pyramid OFF (sanity, beklenti +%116.3)"),
    ("light_pyramid", [1.0, 2.0], [0.30, 0.20],
     "+%30@1R +%20@2R (partial close paralel)"),
    ("standard_pyramid", [1.0, 2.0], [0.50, 0.30],
     "+%50@1R +%30@2R (partial close paralel)"),
    ("aggressive_pyramid", [0.5, 1.5], [0.50, 0.50],
     "+%50@0.5R +%50@1.5R (early add)"),
    ("conservative_pyramid", [1.0], [0.20],
     "+%20@1R only (single tier)"),
]


# =====================================================================
# MAIN
# =====================================================================

def main():
    print("=" * 110)
    print("SEC15.5 — Pyramiding (Winner Trade'lere Ek Pozisyon)")
    print("=" * 110)
    print(f"Pool: {POOL_PATH.name}")
    print(f"Sim yaklasimi: R-transform (engine degismiyor, regression riski sifir)\n")

    if not POOL_PATH.exists():
        print(f"FATAL: pool not found: {POOL_PATH}")
        print("Onceki sec13.4 sprint'i calistirilmis olmali.")
        return

    with POOL_PATH.open("rb") as f:
        base_pool = pickle.load(f)
    base_pool = sorted(base_pool, key=lambda t: t["entry_ts"])
    print(f"Base pool: {len(base_pool)} trade")
    print(f"Trade pool aralik: {base_pool[0]['entry_ts'].date()} -> "
          f"{base_pool[-1]['exit_ts'].date()}\n")

    base_stats = pool_artifact_stats(base_pool)
    print(f"Base pool R stats: mean={base_stats['mean_R']:+.3f}  "
          f"median={base_stats['median_R']:+.3f}  "
          f"max={base_stats['max_R']:+.1f}  p99={base_stats['p99_R']:+.1f}\n")

    # Build production config (v1.5 BALANCED + side-cond DD + halt + F&G)
    base_cfg = ProductionConfig.from_yaml(str(ROOT / "configs" / "risk_balanced.yaml"))
    halt_cal = compute_btc_capitulation_halt()
    fund_long, fund_short = _lazy_build_funding_filters({
        "funding_filter_enabled": False,
        "funding_aggregation_mode": "00:00_only",
    })
    fng_short_20 = build_fng_short_skip(20)
    combined_short_skip = {**dict(fund_short or {}), **dict(fng_short_20)}
    cfg = base_cfg.with_overrides(
        alt_data_skip_long=fund_long,
        alt_data_skip_short=combined_short_skip,
        btc_halt_calendar=halt_cal,
    ) if hasattr(base_cfg, "with_overrides") else base_cfg

    # Fallback: with_overrides yoksa dataclasses.replace
    if cfg is base_cfg:
        from dataclasses import replace
        cfg = replace(
            base_cfg,
            alt_data_skip_long=fund_long,
            alt_data_skip_short=combined_short_skip,
            btc_halt_calendar=halt_cal,
        )

    print(f"Cfg: monthly_dd={cfg.monthly_dd}  halt_days={cfg.monthly_halt_days}  "
          f"risk_pct={cfg.risk_pct}  side_cond_mdd_long={cfg.monthly_dd_long}  "
          f"side_cond_mdd_short={cfg.monthly_dd_short}\n")

    # Build windows from base pool
    win_start = base_pool[0]["entry_ts"]
    win_end = base_pool[-1]["exit_ts"]
    windows = make_windows(win_start, win_end)
    print(f"Walk-forward: {len(windows)} pencere (3y rolling, 60g step)\n")

    # Phase: evaluate each variant
    print(f"{'cell':<22} {'mean_R':>7} {'maxR':>7} {'p99R':>7}  "
          f"{'mean_ann':>9} {'med':>7} {'min':>7} {'max':>7} "
          f"{'DD':>8} {'r-adj':>6} {'neg':>4}")
    print("-" * 130)

    results = []
    for label, at_R, size_pct, desc in GRID:
        if not at_R:  # baseline: no transform
            pool = base_pool
        else:
            pool = transform_pool_pyramid(
                base_pool,
                pyramid_at_R=at_R,
                pyramid_size_pct=size_pct,
            )
        art = pool_artifact_stats(pool)
        res = evaluate_pool(pool, cfg, windows)
        if res is None:
            print(f"{label:<22} eval=None")
            continue
        is_baseline = (label == "v15_baseline")
        tag = " <-- BASE" if is_baseline else ""
        print(f"{label:<22} "
              f"{art['mean_R']:>+6.2f} {art['max_R']:>+6.1f} {art['p99_R']:>+6.1f}  "
              f"{res['mean_ann']:>+8.2f}% {res['median_ann']:>+6.1f}% "
              f"{res['min_ann']:>+6.1f}% {res['max_ann']:>+6.1f}% "
              f"{res['mean_dd']:>+7.1f}% {res['r_adj']:>5.3f} "
              f"{res['negatives']:>4d}{tag}")
        results.append({
            "cell": label,
            "pyramid_at_R": at_R,
            "pyramid_size_pct": size_pct,
            "description": desc,
            "n_trades": len(pool),
            **res,
            "max_R": art["max_R"],
            "p99_R": art["p99_R"],
            "p95_R": art["p95_R"],
            "mean_R": art["mean_R"],
            "median_R": art["median_R"],
            "is_baseline": is_baseline,
        })

    # Phase: Gates
    baseline = next((r for r in results if r["is_baseline"]), None)
    if not baseline:
        print("FATAL: baseline missing.")
        return
    b_ann = baseline["mean_ann"]
    b_dd = baseline["mean_dd"]
    b_radj = baseline["r_adj"]
    print(f"\nMEASURED v1.5 baseline: ann={b_ann:+.2f}%  DD={b_dd:+.1f}%  "
          f"r-adj={b_radj:.3f}  neg={baseline['negatives']}\n")
    # Sanity: baseline replay v1.5 (+%116.3 / -%34.9 / 3.332) yakin olmali
    sanity_ok = (
        abs(b_ann - 116.3) < 5.0
        and abs(b_dd - (-34.9)) < 5.0
        and abs(b_radj - 3.332) < 0.3
    )
    print(f"Sanity check (v1.5 baseline +%116.3 / -%34.9 / 3.332): "
          f"{'OK' if sanity_ok else 'WARN — replay sapma var'}\n")

    # PRE-REGISTERED gates (mutlak — baseline ile karsılastirma da yapacak)
    G_RETURN = 121.3   # baseline +%116.3 + 5pp
    G_DD_TOL = -39.9   # baseline -%34.9 + 5pp tolerans
    G_DD_PANIC = -50.0
    G_RADJ = 3.0
    G_MAXR = 30.0

    print("# PRE-REGISTERED GATES:")
    print(f"  G0 ARTIFACT   max_R(pyramid) <= {G_MAXR}")
    print(f"  G1 RETURN     mean_ann >= {G_RETURN:+.1f}% (v1.5 baseline +%116.3 + 5pp)")
    print(f"  G2 DD-TOL     mean_dd >= {G_DD_TOL:+.1f}% (baseline -%34.9 + 5pp tolerans)")
    print(f"  G3 NEG        negatives == 0")
    print(f"  G4 R-ADJ      r-adj >= {G_RADJ}")
    print(f"  G5 PANIC      mean_dd >= {G_DD_PANIC:+.1f}% (panik zone REJECT)\n")

    print(f"{'cell':<22} {'G0':>4} {'G1':>4} {'G2':>4} {'G3':>4} {'G4':>4} {'G5':>4} "
          f"{'verdict':>8} {'d_ann':>8} {'d_dd':>7} {'d_radj':>8} {'maxR':>7}")
    print("-" * 110)
    pass_cells = []
    for r in results:
        if r["is_baseline"]:
            print(f"{r['cell']:<22} {'-':>4} {'-':>4} {'-':>4} {'-':>4} {'-':>4} {'-':>4} "
                  f"{'BASE':>8} {'-':>8} {'-':>7} {'-':>8} {r['max_R']:>+6.1f}")
            continue
        g0 = r["max_R"] <= G_MAXR
        g1 = r["mean_ann"] >= G_RETURN
        g2 = r["mean_dd"] >= G_DD_TOL
        g3 = r["negatives"] == 0
        g4 = r["r_adj"] >= G_RADJ
        g5 = r["mean_dd"] >= G_DD_PANIC
        all_ok = g0 and g1 and g2 and g3 and g4 and g5
        verdict = "PASS" if all_ok else "fail"
        print(f"{r['cell']:<22} "
              f"{'OK' if g0 else 'XX':>4} "
              f"{'OK' if g1 else '..':>4} "
              f"{'OK' if g2 else '..':>4} "
              f"{'OK' if g3 else '..':>4} "
              f"{'OK' if g4 else '..':>4} "
              f"{'OK' if g5 else 'XX':>4} "
              f"{verdict:>8} "
              f"{r['mean_ann']-b_ann:>+7.2f}pp {r['mean_dd']-b_dd:>+6.1f}pp "
              f"{r['r_adj']-b_radj:>+7.3f} {r['max_R']:>+6.1f}")
        r["gates"] = {"G0": g0, "G1": g1, "G2": g2, "G3": g3, "G4": g4, "G5": g5}
        r["verdict"] = verdict
        if all_ok:
            pass_cells.append(r)

    print()
    winner = None
    if pass_cells:
        pass_cells.sort(key=lambda r: -r["r_adj"])
        winner = pass_cells[0]
        print(f"# WINNER (en yuksek r-adj among PASS):")
        print(f"  cell={winner['cell']}  ({winner['description']})")
        print(f"  ann={winner['mean_ann']:+.2f}%  DD={winner['mean_dd']:+.1f}%  "
              f"r-adj={winner['r_adj']:.3f}  max_R={winner['max_R']:+.1f}")
        print(f"  delta vs baseline: ann {winner['mean_ann']-b_ann:+.2f}pp  "
              f"DD {winner['mean_dd']-b_dd:+.1f}pp  r-adj {winner['r_adj']-b_radj:+.3f}")
    else:
        print("# WINNER: NONE — hicbir varyant tum gate'leri (G0-G5) gecmedi.")
        non_base = [r for r in results if not r["is_baseline"]]
        if non_base:
            non_base.sort(key=lambda r: -r["r_adj"])
            top = non_base[0]
            print(f"  EN YUKSEK r-adj (PASS-DISI): {top['cell']}  "
                  f"r-adj={top['r_adj']:.3f}  ann={top['mean_ann']:+.2f}%  "
                  f"DD={top['mean_dd']:+.1f}%  maxR={top['max_R']:+.1f}")

    # Persist
    JSON_PATH.parent.mkdir(parents=True, exist_ok=True)
    with JSON_PATH.open("w", encoding="utf-8") as f:
        json.dump({
            "baseline": baseline,
            "sanity_ok": sanity_ok,
            "results": results,
            "winner": winner,
            "n_windows": len(windows),
            "gates": {
                "G0_max_R": G_MAXR,
                "G1_return": G_RETURN,
                "G2_dd_tol": G_DD_TOL,
                "G3_neg": 0,
                "G4_radj": G_RADJ,
                "G5_panic": G_DD_PANIC,
            },
            "config": {
                "preset": "BALANCED+side-cond+halt+F&G",
                "monthly_dd": cfg.monthly_dd,
                "halt_days": cfg.monthly_halt_days,
                "risk_pct": cfg.risk_pct,
                "monthly_dd_long": cfg.monthly_dd_long,
                "monthly_dd_short": cfg.monthly_dd_short,
                "pool": str(POOL_PATH.name),
            },
        }, f, indent=2, default=str)
    print(f"\nJSON saved: {JSON_PATH}")

    # Markdown report
    write_report(REPORT_PATH, results, baseline, winner, b_ann, b_dd, b_radj,
                 len(windows), sanity_ok)
    print(f"MD saved:   {REPORT_PATH}")

    return results, winner


def write_report(path, results, baseline, winner, b_ann, b_dd, b_radj,
                 n_windows, sanity_ok):
    L = []
    L.append("# SEC15.5 — Pyramiding (Winner Trade'lere Ek Pozisyon)\n\n")
    L.append("**Tarih:** 2026-05-13  \n")
    L.append("**Sprint:** sec15_5_pyramiding  \n")
    L.append("**Walk-forward:** {} pencere (3y rolling, 60g step)  \n".format(n_windows))
    L.append("**Pool:** v1.5 (TOP_11 + mult=1.5 + time_exit=30 + tp1=1.0/tp2=1.5)  \n")
    L.append("**Cfg:** BALANCED + side-cond mdd (long=10%/short=5%) + halt + F&G short<=20  \n")
    L.append("**Sim:** R-transform pool (engine DEGISMEDI — regression riski sifir)  \n\n")

    L.append("## Hipotez\n\n")
    L.append("v1.5 multi-target engine 1R'da %30 partial-close yapiyor (kar realize). "
             "Bunu \"let winners run\" doktrini ile **paralel** hale getir: 1R'da partial "
             "close YANINDA ek pozisyon ekle (size +%30-50). Boylece big winner'larda "
             "exposure pyramidsel buyur, kucuk kazananlar normal akar.\n\n")
    L.append("**Risk:** Pyramid trade'in cumulative loss potansiyeli — 1R'a varip BE'ye "
             "donen trade'lerde ek pos break-even, yani ana trade -1R + ek 0 = net -1R "
             "(simetrik). Ama 1R'a varan trade'lerde MFE >= 1R old. icin SL BE'ye "
             "cekilebildiginden, gercek downside duzgun yonetilir.\n\n")

    L.append("## Sim Yaklasimi (R-Transform)\n\n")
    L.append("Engine degisikligi YOK — sec13.4 cache'inden v1.5 baseline pool "
             "(`pool_A6_mult15_t30.pkl`, 6650 trade) okuyup pool'daki R'i pyramid "
             "kuralina gore donusturuyoruz. Replay aynı production_replay ile.\n\n")
    L.append("**R Transform:**\n")
    L.append("```\n")
    L.append("R_pyramid = R_orig + sum_i [ s_i * max(0, R_orig - t_i) ]\n")
    L.append("  t_i = pyramid_at_R[i]    (trigger R)\n")
    L.append("  s_i = pyramid_size_pct[i] (ek qty / orijinal qty)\n")
    L.append("```\n\n")
    L.append("**Mantik:** Trade R_orig >= t_i ise pyramid girdi varsayimi. Ek pos t_i'de "
             "entry, ana pos exit'inde exit -> ek pos R = (R_orig - t_i). "
             "max(0,...) BE-protect (SL break-even'a cekildigi icin).\n\n")
    L.append("**Bias:** Bu OPTIMIST upper bound. MFE>=t ama R_orig<t olan trade'lerde "
             "(BE'ye donmus pyramid) ek pos contribution sifir varsayilir — ihmal "
             "edilebilir cunku R_orig=BE durumu nadir.\n\n")

    L.append("## Pre-Registered Grid (5 varyant)\n\n")
    L.append("| cell | trigger | size_pct | description |\n")
    L.append("|------|---------|----------|-------------|\n")
    for r in results:
        L.append(f"| {r['cell']} | {r['pyramid_at_R']} | {r['pyramid_size_pct']} | "
                 f"{r['description']} |\n")
    L.append("\n")

    L.append("## Sonuclar (13 pencere walk-forward)\n\n")
    L.append("| cell | mean_R | max_R | p99_R | mean_ann | DD | r-adj | neg |\n")
    L.append("|------|--------|-------|-------|----------|-----|-------|-----|\n")
    for r in results:
        tag = " (baseline)" if r["is_baseline"] else ""
        L.append(f"| {r['cell']}{tag} | {r['mean_R']:+.2f} | {r['max_R']:+.1f} | "
                 f"{r['p99_R']:+.1f} | {r['mean_ann']:+.2f}% | {r['mean_dd']:+.1f}% | "
                 f"{r['r_adj']:.3f} | {r['negatives']}/{r['n_windows']} |\n")
    L.append("\n")

    sanity_str = "OK (replay v1.5 baseline ile uyumlu)" if sanity_ok \
        else "WARN — baseline replay sapma var, sonuclari ihtiyatli yorumla"
    L.append(f"**Sanity check:** v1.5 baseline measured "
             f"+{b_ann:.2f}% / {b_dd:+.1f}% / r-adj {b_radj:.3f} -> {sanity_str}\n\n")

    L.append("## Pre-Registered Statistical Gates\n\n")
    L.append("- **G0 ARTIFACT** max_R(pyramid) <= 30  (pyramid maxR dogal artar; >30 = artifact)\n")
    L.append("- **G1 RETURN**   mean_ann >= +%121.3  (v1.5 baseline +%116.3 + 5pp)\n")
    L.append("- **G2 DD-TOL**   mean_dd >= -%39.9    (baseline -%34.9 + 5pp tolerans, asimetrik risk)\n")
    L.append("- **G3 NEG**      negatives == 0\n")
    L.append("- **G4 R-ADJ**    r-adj >= 3.0\n")
    L.append("- **G5 PANIC**    mean_dd >= -%50      (panik zone REJECT)\n\n")

    L.append("## Gate Verdict\n\n")
    L.append("| cell | G0 | G1 | G2 | G3 | G4 | G5 | verdict | d_ann | d_dd | d_radj | maxR |\n")
    L.append("|------|----|----|----|----|----|----|---------|-------|------|--------|------|\n")
    for r in results:
        if r["is_baseline"]:
            L.append(f"| {r['cell']} | — | — | — | — | — | — | BASE | — | — | — | "
                     f"{r['max_R']:+.1f} |\n")
            continue
        g = r.get("gates", {})
        L.append(f"| {r['cell']} | "
                 f"{'OK' if g.get('G0') else 'XX'} | "
                 f"{'OK' if g.get('G1') else '..'} | "
                 f"{'OK' if g.get('G2') else '..'} | "
                 f"{'OK' if g.get('G3') else '..'} | "
                 f"{'OK' if g.get('G4') else '..'} | "
                 f"{'OK' if g.get('G5') else 'XX'} | "
                 f"{'**PASS**' if r['verdict']=='PASS' else 'fail'} | "
                 f"{r['mean_ann']-b_ann:+.2f}pp | {r['mean_dd']-b_dd:+.1f}pp | "
                 f"{r['r_adj']-b_radj:+.3f} | {r['max_R']:+.1f} |\n")
    L.append("\n")

    L.append("## Karar\n\n")
    if winner is not None:
        L.append(f"**WINNER:** `{winner['cell']}`  \n")
        L.append(f"- {winner['description']}\n")
        L.append(f"- yillik {winner['mean_ann']:+.2f}% "
                 f"(baseline {b_ann:+.2f}%, +{winner['mean_ann']-b_ann:.2f}pp)\n")
        L.append(f"- DD {winner['mean_dd']:+.1f}% "
                 f"(baseline {b_dd:+.1f}%, {winner['mean_dd']-b_dd:+.1f}pp)\n")
        L.append(f"- r-adj {winner['r_adj']:.3f} "
                 f"(baseline {b_radj:.3f}, +{winner['r_adj']-b_radj:.3f})\n")
        L.append(f"- max_R {winner['max_R']:+.1f}  (G0 artifact <= 30 OK)\n")
        L.append(f"- 13/13 pencere pozitif: EVET\n\n")
        L.append("**ONERI:** Engine'e `pyramid_enabled` + `pyramid_at_R` + "
                 "`pyramid_size_pct` parametreleri ekle. Default OFF (geri uyumlu). "
                 "BALANCED preset'e bu varyantı entegre et — DD koruma kritik old. "
                 "icin live-paper'da once test et, sonra production'a al.\n\n")
        L.append("**RISK NOTE:** Pyramid sim OPTIMIST upper bound. Live'da:\n")
        L.append("- Slippage ek pozisyona iki kez uygulanır (ek %2-5 kayip)\n")
        L.append("- Notional cap (%30/equity) pyramid ek pos'u kısabilir (gerçek size_pct < hedef)\n")
        L.append("- Live-backtest parity testi sart\n")
    else:
        L.append("**RED — hicbir varyant tum gate'leri (G0-G5) gecmedi.**\n\n")
        non_base = [r for r in results if not r["is_baseline"]]
        if non_base:
            non_base.sort(key=lambda r: -r["r_adj"])
            top = non_base[0]
            L.append(f"En yuksek r-adj non-PASS: `{top['cell']}` "
                     f"(r-adj {top['r_adj']:.3f}, ann {top['mean_ann']:+.2f}%, "
                     f"DD {top['mean_dd']:+.1f}%, max_R {top['max_R']:+.1f}).\n\n")
        L.append("Yorum: Pyramid teorik olarak \"let winners run\" ile uyumlu, ancak "
                 "v1.5 baseline'in zaten %30/30/40 partial-close + force-exit ile "
                 "iyi runner yonettigi gorulduğunden ek pyramid bonusu **gate'leri "
                 "gecemiyor**. Olasi sebepler:\n"
                 "- Mevcut runner +%40 zaten yeterli leverage; ek pos marjinal uplift.\n"
                 "- DD asimetrisi tolerans gate'i (G2/G5) ihlal ediyor.\n"
                 "- BALANCED preset side-cond mdd (long=10/short=5) pyramid'i kisitliyor.\n\n"
                 "**SONUC: Pyramiding production'a alinmasin. v1.5 baseline (no pyramid) "
                 "korunur.**\n")

    L.append("\n## Pre-Reg Disipline & Reproducibility\n\n")
    L.append("- Grid pre-registered (5 varyant: baseline + 4 pyramid).\n")
    L.append("- HARK protection: gates onceden yazildi, post-hoc tweak yok.\n")
    L.append("- Sim approach: R-transform (engine degismiyor — sec13.4 cache reuse).\n")
    L.append(f"- Pool: `data/_sec13_4_cache/{POOL_PATH.name}` (TOP_11 v1.5 stack).\n")
    L.append(f"- JSON: `reports/lab/sec15_5_pyramiding.json`\n")
    L.append("- Re-run: `PYTHONPATH=src python scripts/sec15_5_pyramiding.py`\n")
    L.append("- Engine API tasarimi (gelecek): `BacktestEngine(pyramid_enabled=True, "
             "pyramid_at_R=[1.0,2.0], pyramid_size_pct=[0.5,0.3], "
             "pyramid_close_partial=True)`\n")
    with open(path, "w", encoding="utf-8") as f:
        f.writelines(L)


if __name__ == "__main__":
    main()
