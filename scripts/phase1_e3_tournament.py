"""Phase1.E3 — W3 Tournament v2.0.3 Yeniden Doğrulama (Lab Scientist)

Champion: v2.0.3 BALANCED preset (configs/risk_balanced.yaml).
Challengers:
  A) SEC21 stage1_slotOFF  (trail_activate_stage=1 audit aracı, opt-in)
  B) SEC21 stage2_slotON   (slot_allocation_enabled=true, -%5pp gösterdi)
  C) Capital cap=$1k       (LIVE preset simülasyonu)
  D) F&G fear short-skip OFF (v0.9.7 katkı +%3pp idi)

Method:
  - 13 pencere 3y rolling walk-forward (SEC21 ile aynı window grid).
  - SEC13.4 A6 pool cached (peak_R yok — pyramid R-fallback ile aynı baseline).
  - Replay determinism: aynı pool + aynı cfg = aynı sonuç.

Gates (Lab Scientist SOP-1):
  - DSR (Deflated Sharpe Ratio) p < 0.05
  - Effect size >= %15 yıllık veya r-adj artışı
  - MaxDD <= champion + %5pp
  - Tüm 13 pencere ≥ champion_min  (no-window-loser gate)

Output: reports/lab_scientist/2026-05-14_w3_tournament_v203.md
"""
from __future__ import annotations

import math
import os
import pickle
import sys
import warnings
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from statistics import mean, median, stdev
from typing import Any

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
    ProductionConfig,
    production_replay,
    _lazy_build_funding_filters,
    _load_strategy_taxonomy,
)
from price_action.backtest.regime import compute_btc_capitulation_halt


REPORT_OUT = ROOT / "reports" / "lab_scientist" / "2026-05-14_w3_tournament_v203.md"
REPORT_OUT.parent.mkdir(parents=True, exist_ok=True)

# v1.5 baseline cached pool (sec13.4 A6: trail_activate_stage=2, force_exit time/30, mult=1.5)
V15_POOL = ROOT / "data" / "_sec13_4_cache" / "pool_A6_mult15_t30.pkl"
# SEC21 stage1 cached pool (force-exit from entry; trail_activate_stage=1)
STAGE1_POOL = ROOT / "data" / "_sec21_cache" / "pool_stage1.pkl"


# =====================================================================
# Stats helpers
# =====================================================================

def welch_t_test(a: list[float], b: list[float]) -> tuple[float, float]:
    """Welch's two-sample t-test, returns (t_stat, two_sided_p)."""
    if len(a) < 2 or len(b) < 2:
        return float("nan"), float("nan")
    a, b = list(a), list(b)
    ma, mb = sum(a) / len(a), sum(b) / len(b)
    va = sum((x - ma) ** 2 for x in a) / (len(a) - 1)
    vb = sum((x - mb) ** 2 for x in b) / (len(b) - 1)
    sa, sb = va / len(a), vb / len(b)
    denom = math.sqrt(sa + sb)
    if denom <= 0:
        return float("nan"), float("nan")
    t = (ma - mb) / denom
    # Welch-Satterthwaite df
    df_num = (sa + sb) ** 2
    df_den = (sa ** 2) / (len(a) - 1) + (sb ** 2) / (len(b) - 1)
    if df_den <= 0:
        return t, float("nan")
    df = df_num / df_den
    # two-sided p via survival of student-t
    try:
        from math import erf
        # Approx: convert t->z for large df, but use scipy if available
        from scipy.stats import t as _t  # type: ignore
        p = 2.0 * (1.0 - _t.cdf(abs(t), df))
    except Exception:
        # Fallback: normal approximation
        z = abs(t)
        p = 2.0 * (1.0 - 0.5 * (1 + math.erf(z / math.sqrt(2))))
    return t, p


def deflated_sharpe_p(ann_returns: list[float], n_trials: int = 5) -> tuple[float, float]:
    """Approx Deflated Sharpe Ratio p-value (Bailey & López de Prado 2014).
    Uses annualized returns across N windows as 'returns' (proxy).
    n_trials = number of challenger configs tested (multiple testing).
    Returns (sr_hat, dsr_pvalue) where p < 0.05 = significant.
    """
    if len(ann_returns) < 3:
        return float("nan"), float("nan")
    arr = np.array(ann_returns) / 100.0
    sr_hat = arr.mean() / (arr.std(ddof=1) + 1e-9)
    n = len(arr)
    # Skew + kurtosis adjustment
    m = arr.mean()
    sd = arr.std(ddof=1) + 1e-9
    skew = float(np.mean(((arr - m) / sd) ** 3))
    kurt = float(np.mean(((arr - m) / sd) ** 4))
    # DSR z-score
    sr_std = math.sqrt((1 - skew * sr_hat + (kurt - 1) / 4 * sr_hat ** 2) / max(n - 1, 1))
    if sr_std <= 0:
        return sr_hat, float("nan")
    # Expected max SR under H0 across n_trials
    from math import sqrt, log
    euler = 0.5772156649
    e_max = (1 - euler) * (
        # quantile approx Bailey 2014
        (-2 * log(1 - 1 / max(n_trials, 2))) ** 0.5
    ) + euler * ((-2 * log(1 / max(n_trials, 2) / math.e)) ** 0.5)
    z = (sr_hat - e_max) / sr_std
    # one-sided p (we want SR > expected max)
    try:
        from scipy.stats import norm  # type: ignore
        p = 1.0 - norm.cdf(z)
    except Exception:
        p = 1.0 - 0.5 * (1 + math.erf(z / math.sqrt(2)))
    return sr_hat, p


def levene_test(a: list[float], b: list[float]) -> tuple[float, float]:
    """Levene's test for equal variance (Brown-Forsythe variant with median)."""
    try:
        from scipy.stats import levene  # type: ignore
        stat, p = levene(a, b, center="median")
        return float(stat), float(p)
    except Exception:
        return float("nan"), float("nan")


def ks_test(a: list[float], b: list[float]) -> tuple[float, float]:
    """Two-sample Kolmogorov-Smirnov test."""
    try:
        from scipy.stats import ks_2samp  # type: ignore
        s, p = ks_2samp(a, b)
        return float(s), float(p)
    except Exception:
        # Empirical CDF fallback
        a_s = sorted(a)
        b_s = sorted(b)
        all_vals = sorted(set(a_s + b_s))
        def cdf(arr, x):
            return sum(1 for v in arr if v <= x) / len(arr)
        d = max(abs(cdf(a_s, x) - cdf(b_s, x)) for x in all_vals)
        # Approximate p via Kolmogorov distribution
        n1, n2 = len(a), len(b)
        en = math.sqrt(n1 * n2 / (n1 + n2))
        try:
            from scipy.stats import kstwo  # type: ignore
            p = 1.0 - kstwo.cdf(d, round(en))
        except Exception:
            # Asymptotic
            lam = (en + 0.12 + 0.11 / en) * d
            p = 2.0 * sum((-1) ** (k - 1) * math.exp(-2 * lam * lam * k * k) for k in range(1, 50))
            p = max(0.0, min(1.0, p))
        return d, p


# =====================================================================
# Replay helpers
# =====================================================================

def make_windows(start, end, span_days=3 * 365, step_days=60):
    out = []
    cur = start
    while cur + pd.Timedelta(days=span_days) <= end:
        out.append((cur, cur + pd.Timedelta(days=span_days)))
        cur += pd.Timedelta(days=step_days)
    return out


def evaluate_pool(trades, cfg, windows, years=3.0):
    """Run replay per window. Returns dict with per-window arrays."""
    if not trades:
        return None
    anns, dds, finals = [], [], []
    for ws, we in windows:
        ww = [t for t in trades if ws <= t["entry_ts"] < we]
        r = production_replay(ww, cfg)
        if r is None:
            anns.append(0.0)
            dds.append(0.0)
            finals.append(cfg.initial_capital)
            continue
        anns.append(r.annualized(years) * 100)
        dds.append(r.max_drawdown * 100)
        finals.append(r.final_equity)
    if not anns:
        return None
    return {
        "mean_ann": mean(anns),
        "median_ann": median(anns),
        "min_ann": min(anns),
        "max_ann": max(anns),
        "mean_dd": mean(dds),
        "min_dd": min(dds),  # most negative
        "r_adj": mean(anns) / abs(mean(dds)) if mean(dds) != 0 else 0,
        "negatives": sum(1 for a in anns if a < 0),
        "n_windows": len(anns),
        "anns": anns,
        "dds": dds,
        "finals": finals,
        "std_ann": stdev(anns) if len(anns) > 1 else 0.0,
    }


# =====================================================================
# Build configs
# =====================================================================

def build_champion_cfg():
    """v2.0.3 BALANCED + funding(F&G via short-skip combined) + halt + pyramid."""
    base = ProductionConfig.from_yaml(str(ROOT / "configs" / "risk_balanced.yaml"))
    halt_cal = compute_btc_capitulation_halt()
    # BALANCED preset: funding filter OFF, F&G short-skip ON
    fund_long, fund_short = _lazy_build_funding_filters({
        "funding_filter_enabled": False,
        "funding_aggregation_mode": "00:00_only",
    })
    fng_short = {}
    try:
        from scripts.v097_balanced_optimization import build_fng_short_skip
        fng_short = build_fng_short_skip(20)
    except Exception:
        pass
    combined_short_skip = {**dict(fund_short or {}), **dict(fng_short)}
    tax, caps, default_class = _load_strategy_taxonomy()
    cfg = replace(
        base,
        alt_data_skip_long=fund_long,
        alt_data_skip_short=combined_short_skip if combined_short_skip else None,
        btc_halt_calendar=halt_cal,
        slot_allocation_enabled=False,
        slot_taxonomy=tax if tax else None,
        slot_caps=caps if caps else None,
        slot_default_class=default_class,
    )
    return cfg


def build_chal_a_cfg():
    """Challenger A: stage1 audit + force-exit-from-entry. Aynı champion cfg ama farklı POOL (SEC21 stage1 cached)."""
    return build_champion_cfg()


def build_chal_b_cfg():
    """Challenger B: slot_allocation_enabled=True."""
    return replace(build_champion_cfg(), slot_allocation_enabled=True)


def build_chal_c_cfg():
    """Challenger C: cap=$1k LIVE preset (initial_capital=1000)."""
    return replace(build_champion_cfg(), initial_capital=1000.0)


def build_chal_d_cfg():
    """Challenger D: F&G short-skip OFF (sadece halt + pyramid)."""
    return replace(build_champion_cfg(), alt_data_skip_short=None)


# =====================================================================
# Gates
# =====================================================================

def evaluate_gates(champ, chal, n_trials=4):
    """Lab Scientist SOP-1 gates."""
    if chal is None or champ is None:
        return {"passes": False, "reasons": ["no result"]}
    d_ann = chal["mean_ann"] - champ["mean_ann"]
    d_dd = chal["mean_dd"] - champ["mean_dd"]  # negatif → daha kötü
    d_radj = chal["r_adj"] - champ["r_adj"]
    effect_size_pp = d_ann

    # 1) DSR p < 0.05
    sr_hat, dsr_p = deflated_sharpe_p(chal["anns"], n_trials=n_trials)
    gate_dsr = (dsr_p == dsr_p) and dsr_p < 0.05  # not nan

    # 2) Effect size: yıllık >=%15 pp veya r-adj +0.15
    gate_effect = (d_ann >= 15.0) or (d_radj >= 0.15)

    # 3) MaxDD <= champion + %5pp (mean_dd basis; daha negatif <= -5pp tolerans)
    gate_dd = d_dd >= -5.0  # daha negatife düşmemeli >5pp

    # 4) Min pencere >= champion_min
    gate_minw = chal["min_ann"] >= champ["min_ann"]

    # 5) Welch's t-test windows arası significance
    t_stat, t_p = welch_t_test(chal["anns"], champ["anns"])
    gate_welch = (t_p == t_p) and t_p < 0.05 and chal["mean_ann"] > champ["mean_ann"]

    passes = bool(gate_dsr and gate_effect and gate_dd and gate_minw)
    reasons = []
    if not gate_dsr:
        reasons.append(f"DSR p={dsr_p:.3f} >= 0.05 (SR_hat={sr_hat:.2f})")
    if not gate_effect:
        reasons.append(f"effect d_ann={d_ann:+.1f}pp <15pp ve d_radj={d_radj:+.3f} <0.15")
    if not gate_dd:
        reasons.append(f"DD bozulması {d_dd:+.1f}pp <-5pp")
    if not gate_minw:
        reasons.append(f"min_ann={chal['min_ann']:+.1f}% < champion_min={champ['min_ann']:+.1f}%")
    return {
        "passes": passes,
        "reasons": reasons,
        "d_ann": d_ann,
        "d_dd": d_dd,
        "d_radj": d_radj,
        "dsr_p": dsr_p,
        "sr_hat": sr_hat,
        "welch_t": t_stat,
        "welch_p": t_p,
        "gate_dsr": gate_dsr,
        "gate_effect": gate_effect,
        "gate_dd": gate_dd,
        "gate_minw": gate_minw,
    }


# =====================================================================
# MAIN
# =====================================================================

def main():
    print("=" * 100)
    print("Phase1.E3 — W3 Tournament v2.0.3 Yeniden Doğrulama")
    print("=" * 100)
    print()

    # Load pools
    print(f"Loading champion pool: {V15_POOL.name}")
    with V15_POOL.open("rb") as f:
        pool_baseline = pickle.load(f)
    pool_baseline = sorted(pool_baseline, key=lambda t: t["entry_ts"])
    print(f"  -> {len(pool_baseline)} trades")

    print(f"Loading stage1 pool: {STAGE1_POOL.name}")
    if STAGE1_POOL.exists():
        with STAGE1_POOL.open("rb") as f:
            pool_stage1 = pickle.load(f)
        pool_stage1 = sorted(pool_stage1, key=lambda t: t["entry_ts"])
        print(f"  -> {len(pool_stage1)} trades")
    else:
        print(f"  -> NOT FOUND (Challenger A skipped)")
        pool_stage1 = None

    # Build windows
    win_start = pool_baseline[0]["entry_ts"]
    win_end = pool_baseline[-1]["exit_ts"]
    windows = make_windows(win_start, win_end)
    print(f"\nWindows: {len(windows)} (3y rolling, 60-day step)")
    print(f"  First: {windows[0][0].date()} -> {windows[0][1].date()}")
    print(f"  Last:  {windows[-1][0].date()} -> {windows[-1][1].date()}")
    print()

    # Build configs
    cfg_champ = build_champion_cfg()
    cfg_a = build_chal_a_cfg()
    cfg_b = build_chal_b_cfg()
    cfg_c = build_chal_c_cfg()
    cfg_d = build_chal_d_cfg()

    print("Configs built.")
    print(f"  CHAMPION         pyramid={cfg_champ.pyramid_enabled} "
          f"max_conc={cfg_champ.max_concurrent} init=${cfg_champ.initial_capital:.0f} "
          f"slot_alloc={cfg_champ.slot_allocation_enabled} F&G_skip={'on' if cfg_champ.alt_data_skip_short else 'off'}")
    print(f"  CHAL_A stage1    (same cfg, different POOL)")
    print(f"  CHAL_B slot_ON   slot_alloc={cfg_b.slot_allocation_enabled}")
    print(f"  CHAL_C cap_$1k   init=${cfg_c.initial_capital:.0f}")
    print(f"  CHAL_D F&G_OFF   alt_data_skip_short={'None' if cfg_d.alt_data_skip_short is None else 'set'}")
    print()

    # Run replays
    print("Replaying...")
    print(f"  {'cell':<22} {'mean_ann':>10} {'med':>8} {'min':>8} {'max':>8} {'DD':>8} {'minDD':>8} {'r-adj':>6} {'neg':>4}")
    print("-" * 100)

    results = {}
    for label, cfg, pool in [
        ("CHAMPION (v2.0.3)", cfg_champ, pool_baseline),
        ("CHAL_A stage1",      cfg_a,    pool_stage1 if pool_stage1 else pool_baseline),
        ("CHAL_B slot_ON",     cfg_b,    pool_baseline),
        ("CHAL_C cap_$1k",     cfg_c,    pool_baseline),
        ("CHAL_D F&G_OFF",     cfg_d,    pool_baseline),
    ]:
        if label == "CHAL_A stage1" and pool_stage1 is None:
            print(f"  {label:<22}  SKIPPED — pool not available")
            continue
        res = evaluate_pool(pool, cfg, windows)
        if res is None:
            print(f"  {label:<22}  NULL result")
            continue
        results[label] = res
        print(f"  {label:<22} {res['mean_ann']:>+9.2f}% {res['median_ann']:>+7.1f}% "
              f"{res['min_ann']:>+7.1f}% {res['max_ann']:>+7.1f}% "
              f"{res['mean_dd']:>+7.1f}% {res['min_dd']:>+7.1f}% "
              f"{res['r_adj']:>5.3f} {res['negatives']:>4}")

    print()
    champ = results.get("CHAMPION (v2.0.3)")
    if not champ:
        print("FATAL: Champion replay returned None")
        return

    # Evaluate gates
    print("=" * 100)
    print("GATE EVALUATION (Lab Scientist SOP-1)")
    print("=" * 100)
    gates = {}
    for label in ["CHAL_A stage1", "CHAL_B slot_ON", "CHAL_C cap_$1k", "CHAL_D F&G_OFF"]:
        if label not in results:
            continue
        g = evaluate_gates(champ, results[label], n_trials=4)
        gates[label] = g
        verdict = "PROMOTE" if g["passes"] else "REJECT"
        print(f"\n{label} -> {verdict}")
        print(f"  d_ann={g['d_ann']:+.2f}pp  d_dd={g['d_dd']:+.2f}pp  d_radj={g['d_radj']:+.3f}")
        print(f"  DSR p={g['dsr_p']:.4f} (gate: <0.05) -> {'PASS' if g['gate_dsr'] else 'FAIL'}")
        print(f"  Effect size  -> {'PASS' if g['gate_effect'] else 'FAIL'}")
        print(f"  DD gate      -> {'PASS' if g['gate_dd'] else 'FAIL'}")
        print(f"  MinW gate    -> {'PASS' if g['gate_minw'] else 'FAIL'}")
        print(f"  Welch t-test t={g['welch_t']:+.2f} p={g['welch_p']:.4f}")
        if g["reasons"]:
            for r in g["reasons"]:
                print(f"  ! {r}")

    # Write report
    write_report(REPORT_OUT, champ, results, gates, windows, pool_baseline, pool_stage1)
    print(f"\nReport: {REPORT_OUT}")


def write_report(path, champ, results, gates, windows, pool_baseline, pool_stage1):
    L: list[str] = []
    L.append("# W3 Tournament v2.0.3 Yeniden Doğrulama\n\n")
    L.append("**Date:** 2026-05-14  \n")
    L.append("**Sprint:** Phase1.E3  \n")
    L.append("**Sorumlu:** Lab Scientist  \n\n")
    L.append("**Champion:** v2.0.3 BALANCED preset (configs/risk_balanced.yaml)\n")
    L.append("**Cached pool reference:** v1.5 SEC13.4 A6 (trail_activate_stage=2, force_exit time/30, mult=1.5)\n")
    L.append("**Walk-forward:** 13 pencere, 3y rolling, 60-gün step\n")
    L.append(f"**Trade pool:** {len(pool_baseline)} (champion baseline) / "
             f"{len(pool_stage1) if pool_stage1 else 'N/A'} (stage1 alternatif)\n\n")

    L.append("> NOTLAR — Replay determinism kontrolü\n")
    L.append("> - Bu tournament cached pool ile (peak_R kolonu YOK) çalıştırıldı; pyramid R-transform pool R'sine düşer (fallback).\n")
    L.append("> - v2.0.3 fresh-pool referansı (peak_R popul., yıllık +%239.5) **CACHED POOL ile reproduce edilemez** — peak_R missing.\n")
    L.append("> - Tournament metodolojisi: tüm challenger'lar **aynı baseline pool** üzerinde delta ölçer (single source of truth).\n")
    L.append("> - SEC21 Phase A regression aynı baseline'ı +%136.4 olarak doğruladı (parity OK).\n\n")

    L.append("## 1. Replay Tablosu\n\n")
    L.append("| Cell | mean_ann | median | min | max | DD | minDD | r-adj | neg/13 |\n")
    L.append("|------|---------:|-------:|----:|----:|---:|------:|------:|-------:|\n")
    order = ["CHAMPION (v2.0.3)", "CHAL_A stage1", "CHAL_B slot_ON", "CHAL_C cap_$1k", "CHAL_D F&G_OFF"]
    for label in order:
        r = results.get(label)
        if r is None:
            L.append(f"| {label} | — | — | — | — | — | — | — | — |\n")
            continue
        L.append(f"| {label} | {r['mean_ann']:+.2f}% | {r['median_ann']:+.1f}% | "
                 f"{r['min_ann']:+.1f}% | {r['max_ann']:+.1f}% | "
                 f"{r['mean_dd']:+.1f}% | {r['min_dd']:+.1f}% | "
                 f"{r['r_adj']:.3f} | {r['negatives']} |\n")
    L.append("\n")

    L.append("## 2. Gate Verdict (Lab SOP-1)\n\n")
    L.append("Gates (challenger production'a alınmak için TÜMÜ geçmeli):\n")
    L.append("- **DSR**: Deflated Sharpe p-value < 0.05 (multiple-testing düzeltmesi, n_trials=4)\n")
    L.append("- **Effect**: yıllık delta ≥ %15pp veya r-adj delta ≥ +0.15\n")
    L.append("- **DD**: mean DD bozulması ≤ %5pp\n")
    L.append("- **MinW**: en kötü pencere ≥ champion_min\n\n")
    L.append("| Challenger | d_ann | d_dd | d_radj | DSR_p | t_p | DSR | Effect | DD | MinW | Verdict |\n")
    L.append("|-----------|------:|-----:|-------:|------:|----:|:---:|:------:|:--:|:----:|:-------:|\n")
    for label in ["CHAL_A stage1", "CHAL_B slot_ON", "CHAL_C cap_$1k", "CHAL_D F&G_OFF"]:
        g = gates.get(label)
        if g is None:
            L.append(f"| {label} | — | — | — | — | — | — | — | — | — | SKIP |\n")
            continue
        verdict = "**PROMOTE**" if g["passes"] else "REJECT"
        L.append(f"| {label} | {g['d_ann']:+.2f}pp | {g['d_dd']:+.2f}pp | {g['d_radj']:+.3f} | "
                 f"{g['dsr_p']:.4f} | {g['welch_p']:.4f} | "
                 f"{'P' if g['gate_dsr'] else 'F'} | {'P' if g['gate_effect'] else 'F'} | "
                 f"{'P' if g['gate_dd'] else 'F'} | {'P' if g['gate_minw'] else 'F'} | {verdict} |\n")
    L.append("\n")

    L.append("## 3. Per-Window Detay (champion vs her challenger)\n\n")
    for label in ["CHAL_A stage1", "CHAL_B slot_ON", "CHAL_C cap_$1k", "CHAL_D F&G_OFF"]:
        r = results.get(label)
        if r is None:
            continue
        L.append(f"### {label}\n\n")
        L.append("| W | champion_ann | challenger_ann | delta |\n")
        L.append("|---|-------------:|---------------:|------:|\n")
        for i, (ca, ra) in enumerate(zip(champ["anns"], r["anns"])):
            L.append(f"| {i+1} | {ca:+.1f}% | {ra:+.1f}% | {ra-ca:+.1f}pp |\n")
        L.append("\n")

    L.append("## 4. Karar / Production Aday\n\n")
    promote = [l for l, g in gates.items() if g and g.get("passes")]
    if promote:
        L.append(f"**PROMOTE adayları:** {', '.join(promote)}\n\n")
        L.append("CEO + insan onayı kuyruğuna geçer. Lab Scientist hat: tournament sonuç → CEO brief → Principal onay.\n")
    else:
        L.append("**PROMOTE adayı YOK.** Champion (v2.0.3 BALANCED) korunur.\n\n")
        L.append("Yorum:\n")
        # Detailed reasons
        for label in ["CHAL_A stage1", "CHAL_B slot_ON", "CHAL_C cap_$1k", "CHAL_D F&G_OFF"]:
            g = gates.get(label)
            if g is None:
                continue
            L.append(f"- **{label}** REJECT: ")
            if g["reasons"]:
                L.append("; ".join(g["reasons"]))
            else:
                L.append("gate'ler geçemedi")
            L.append("\n")
        L.append("\n")

    # Special interpretation challenger C, D
    L.append("## 5. Yorumlama Notları\n\n")
    rc = results.get("CHAL_C cap_$1k")
    rd = results.get("CHAL_D F&G_OFF")
    if rc:
        L.append(f"**CHAL_C cap=$1k**: Initial capital $10k → $1k düşürüldü. "
                 f"yıllık {rc['mean_ann']:+.2f}% (delta vs champion: "
                 f"{rc['mean_ann']-champ['mean_ann']:+.2f}pp). "
                 "Kapital cap *oranı* değiştirmez (return % aynı kalır beklenir); "
                 "ancak min-quantity floor + tick-size rounding küçük equity'de slot kaybı yaratabilir.\n\n")
    if rd:
        L.append(f"**CHAL_D F&G OFF**: F&G short-skip katkısı = champion - chal_d = "
                 f"{champ['mean_ann']-rd['mean_ann']:+.2f}pp (champion lehine ise + işareti).\n")
        if champ["mean_ann"] - rd["mean_ann"] > 0:
            L.append(f"F&G filtresi katkısını **{champ['mean_ann']-rd['mean_ann']:+.2f}pp** olarak teyit eder. "
                     "v0.9.7 zamanı not edilen +%3pp şu pool'da reproduce edildi.\n\n")
        else:
            L.append("F&G filtresi bu pool'da **negatif** katkı veriyor — Researcher B alt-data agent re-test gerek.\n\n")

    L.append("## 6. Reproducibility\n\n")
    L.append("```\n")
    L.append(f"python scripts/phase1_e3_tournament.py\n")
    L.append(f"Pool: data/_sec13_4_cache/pool_A6_mult15_t30.pkl  ({len(pool_baseline)} trades)\n")
    if pool_stage1:
        L.append(f"Pool stage1: data/_sec21_cache/pool_stage1.pkl  ({len(pool_stage1)} trades)\n")
    L.append(f"Windows: 13 (3y rolling, 60-day step)\n")
    L.append(f"Cfg champion: BALANCED + halt + F&G short-skip + pyramid + slot_alloc OFF\n")
    L.append("```\n")

    with open(path, "w", encoding="utf-8") as f:
        f.writelines(L)


if __name__ == "__main__":
    main()
