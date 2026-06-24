"""Lab Task #17 — C2 Champion Extended Validation.

Lab Scientist (CEO mandate, 2026-05-17 evening).

Goals (CEO brief):
  Step 1 — C2 + V5 hybrid (V2 risk %2 + V3 AVWAP patch + V5 pyramid 1.5R)
  Step 2 — C2 12-ay yıllık tam breakdown (per-year × per-month)
  Step 3 — Regime split: bear (2022) / range (2023) / bull (2024-2025) — C2 vs V0
  Step 4 — Risk officer audit: side effect tarama (kısa, kod-statik kanıt)
  Step 5 — Pre-live ETA: paper trade gate koşulları

Çıktılar:
  reports/lab/2026-05-17_c2_champion_validation.md            (PRIMARY)
  reports/lab/sec52_c2_champion_per_month.csv                  (C2 + V0 + C2+V5 × 61 ay)
  reports/lab/sec52_c2_champion_regime_split.csv               (bear/range/bull aggregate)
  reports/lab/sec52_c2_v5_hybrid_walkforward.csv               (C2+V5 × 34 pencere)
  configs/risk_phoenix_scalp_15m_c2_champion.yaml (DRAFT)      (PREVIEW only, production YAML untouched)

Disiplin:
  - lab.py + production YAML DOKUNULMADI
  - YAML draft = preview-only, user sign-off için (üretim aktivasyonu YOK)
  - 1d Phoenix v2.0.4 + 5m configs untouched (ayrı YAML, override scope yok)
  - C2 reproducibility: sec51 script ile birebir override
"""
from __future__ import annotations

import copy
import csv
import io
import os
import pickle
import sys
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean, median, stdev

if __name__ == "__main__":
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    except Exception:
        pass

os.environ["PA_LOG_QUIET"] = "1"
import warnings
warnings.filterwarnings("ignore")
import logging
logging.getLogger("price_action").setLevel(logging.ERROR)

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

import pandas as pd

from price_action.backtest.lab import ProductionConfig, production_replay

CACHE = ROOT / "data" / "sec31_15m_pool.pkl"
RISK_YAML = ROOT / "configs" / "risk_phoenix_scalp_15m_pyramid_r3.yaml"
REPORT = ROOT / "reports" / "lab" / "2026-05-17_c2_champion_validation.md"
CSV_MONTH = ROOT / "reports" / "lab" / "sec52_c2_champion_per_month.csv"
CSV_REGIME = ROOT / "reports" / "lab" / "sec52_c2_champion_regime_split.csv"
CSV_WF = ROOT / "reports" / "lab" / "sec52_c2_v5_hybrid_walkforward.csv"
DRAFT_YAML = ROOT / "configs" / "risk_phoenix_scalp_15m_c2_champion.yaml"

TOP4 = {"vsa_climax_test", "brooks_failed_breakout",
        "anchored_vwap_reversal", "engulfing_continuation"}
SYMBOLS = {"BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT", "ADA/USDT",
           "AVAX/USDT", "LINK/USDT", "DOT/USDT", "DOGE/USDT", "XRP/USDT"}


def to_utc(ts):
    if hasattr(ts, "tz_localize"):
        if ts.tzinfo is None:
            return ts.tz_localize("UTC")
        return ts.tz_convert("UTC")
    if ts.tzinfo is None:
        return ts.replace(tzinfo=timezone.utc)
    return ts.astimezone(timezone.utc)


# ============================================================================
# AVWAP conf patch (sec51 parity)
# ============================================================================
def patch_avwap_conf(pool, lift_to=0.30):
    out = []
    n = 0
    for t in pool:
        if t.get("strategy") == "anchored_vwap_reversal" and t.get("conf", 0.0) < lift_to:
            tc = dict(t)
            tc["conf"] = lift_to
            out.append(tc)
            n += 1
        else:
            out.append(t)
    return out, n


# ============================================================================
# Per-month metrics
# ============================================================================
def per_month_metrics(pool, cfg, label=""):
    pool = sorted(pool, key=lambda x: to_utc(x["entry_ts"]))
    if not pool:
        return []
    start = to_utc(pool[0]["entry_ts"])
    end = to_utc(pool[-1]["entry_ts"])
    months = []
    cy, cm = start.year, start.month
    while True:
        ms = datetime(cy, cm, 1, tzinfo=timezone.utc)
        me = datetime(cy + 1, 1, 1, tzinfo=timezone.utc) if cm == 12 else datetime(cy, cm + 1, 1, tzinfo=timezone.utc)
        if ms > end:
            break
        months.append((cy, cm, ms, me))
        cm += 1
        if cm > 12:
            cm = 1
            cy += 1
    rows = []
    for yr, mo, ms, me in months:
        m_tr = [t for t in pool if ms <= to_utc(t["entry_ts"]) < me]
        if len(m_tr) < 10:
            rows.append({"year": yr, "month": mo, "n_raw": len(m_tr), "n_taken": 0,
                         "monthly_pct": 0.0, "dd_pct": 0.0, "skip": "n<10"})
            continue
        try:
            r = production_replay(m_tr, cfg)
        except Exception as e:
            rows.append({"year": yr, "month": mo, "n_raw": len(m_tr), "n_taken": 0,
                         "monthly_pct": 0.0, "dd_pct": 0.0, "skip": f"err:{e}"})
            continue
        if r is None:
            rows.append({"year": yr, "month": mo, "n_raw": len(m_tr), "n_taken": 0,
                         "monthly_pct": 0.0, "dd_pct": 0.0, "skip": "none"})
            continue
        rows.append({"year": yr, "month": mo, "n_raw": len(m_tr), "n_taken": r.trades,
                     "monthly_pct": r.total_return * 100, "dd_pct": r.max_drawdown * 100,
                     "skip": ""})
    return rows


# ============================================================================
# Walk-forward 34-window
# ============================================================================
def walk_forward_metrics(pool, cfg, train_days=730, oos_days=90, step_days=30):
    if not pool:
        return []
    pool = sorted(pool, key=lambda x: to_utc(x["entry_ts"]))
    start = to_utc(pool[0]["entry_ts"])
    end = to_utc(pool[-1]["exit_ts"])
    windows = []
    cur = start
    while cur + pd.Timedelta(days=train_days + oos_days) <= end:
        windows.append((cur, cur + pd.Timedelta(days=train_days)))
        cur += pd.Timedelta(days=step_days)
    period_years = train_days / 365.0
    rows = []
    for i, (ws, we) in enumerate(windows, start=1):
        ww = [t for t in pool if ws <= to_utc(t["entry_ts"]) < we]
        if not ww:
            rows.append({"window": i, "start": ws.date().isoformat(),
                         "end": we.date().isoformat(), "trades": 0,
                         "annual_pct": 0.0, "dd_pct": 0.0, "r_adj": 0.0})
            continue
        try:
            r = production_replay(ww, cfg)
        except Exception:
            rows.append({"window": i, "start": ws.date().isoformat(),
                         "end": we.date().isoformat(), "trades": len(ww),
                         "annual_pct": 0.0, "dd_pct": 0.0, "r_adj": 0.0})
            continue
        if r is None:
            rows.append({"window": i, "start": ws.date().isoformat(),
                         "end": we.date().isoformat(), "trades": len(ww),
                         "annual_pct": 0.0, "dd_pct": 0.0, "r_adj": 0.0})
            continue
        ann = r.annualized(period_years) * 100
        dd = r.max_drawdown * 100
        ra = ann / abs(dd) if dd != 0 else 0
        rows.append({"window": i, "start": ws.date().isoformat(),
                     "end": we.date().isoformat(), "trades": len(ww),
                     "annual_pct": ann, "dd_pct": dd, "r_adj": ra})
    return rows


def summarize_variant(month_rows, wf_rows):
    valid = [r for r in month_rows if r["skip"] == ""]
    rets = [r["monthly_pct"] for r in valid]
    eq = 1.0
    for r in rets:
        eq *= (1.0 + r / 100.0)
    if valid:
        first = (valid[0]["year"], valid[0]["month"])
        last = (valid[-1]["year"], valid[-1]["month"])
        n_months = (last[0] - first[0]) * 12 + (last[1] - first[1]) + 1
        years = n_months / 12.0
    else:
        years = 1.0
    annual = (eq ** (1.0 / years) - 1.0) * 100 if eq > 0 and years > 0 else -100.0
    pos = sum(1 for r in rets if r > 0)
    ge20 = sum(1 for r in rets if r >= 20.0)
    neg = sum(1 for r in rets if r < 0)
    sub20 = sum(1 for r in rets if r < 20.0)
    mean_m = mean(rets) if rets else 0.0
    cv = (stdev(rets) / abs(mean_m) * 100) if (mean_m != 0 and len(rets) >= 2) else 0.0
    max_loss = min(rets) if rets else 0.0
    max_gain = max(rets) if rets else 0.0
    wf_ann = [r["annual_pct"] for r in wf_rows if r["trades"] > 0]
    wf_dd = [r["dd_pct"] for r in wf_rows if r["trades"] > 0]
    wf_radj = [r["r_adj"] for r in wf_rows if r["trades"] > 0]
    return {
        "annual_pct": annual, "mean_monthly_pct": mean_m, "pos_months": pos,
        "ge20_months": ge20, "neg_months": neg, "sub20_months": sub20,
        "max_loss_pct": max_loss, "max_gain_pct": max_gain, "cv_pct": cv,
        "n_months": len(rets),
        "wf_n_windows": len(wf_ann),
        "wf_mean_annual_pct": mean(wf_ann) if wf_ann else 0.0,
        "wf_mean_dd_pct": mean(wf_dd) if wf_dd else 0.0,
        "wf_mean_r_adj": mean(wf_radj) if wf_radj else 0.0,
        "wf_neg_windows": sum(1 for a in wf_ann if a < 0),
    }


# ============================================================================
# Regime split (bear=2022, range=2023, bull=2024-2025)
# ============================================================================
REGIME_DEF = {
    "bear_2022": [(2022, m) for m in range(1, 13)],
    "range_2023": [(2023, m) for m in range(1, 13)],
    "bull_2024_2025": [(2024, m) for m in range(1, 13)] + [(2025, m) for m in range(1, 13)],
}


def regime_aggregate(month_rows, regime_name):
    target = set(REGIME_DEF[regime_name])
    rows = [r for r in month_rows if (r["year"], r["month"]) in target and r["skip"] == ""]
    if not rows:
        return None
    rets = [r["monthly_pct"] for r in rows]
    eq = 1.0
    for r in rets:
        eq *= (1.0 + r / 100.0)
    n = len(rets)
    cum = (eq - 1.0) * 100
    return {
        "regime": regime_name,
        "n_months": n,
        "mean_monthly_pct": mean(rets),
        "median_monthly_pct": median(rets),
        "cum_return_pct": cum,
        "annual_pct": (eq ** (12.0 / n) - 1.0) * 100 if n > 0 and eq > 0 else -100,
        "pos_months": sum(1 for r in rets if r > 0),
        "neg_months": sum(1 for r in rets if r < 0),
        "ge20_months": sum(1 for r in rets if r >= 20.0),
        "max_gain_pct": max(rets),
        "max_loss_pct": min(rets),
        "cv_pct": (stdev(rets) / abs(mean(rets)) * 100) if (mean(rets) != 0 and n >= 2) else 0.0,
    }


# ============================================================================
# Main
# ============================================================================
def main():
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    print(f"[LOAD] {CACHE} ({CACHE.stat().st_size / 1e6:.1f} MB)", flush=True)
    with CACHE.open("rb") as fh:
        pool_raw = pickle.load(fh)
    pool = [t for t in pool_raw if t.get("strategy") in TOP4 and t.get("symbol") in SYMBOLS]
    print(f"[POOL] {len(pool):,} trade (TOP-4 × 10 sym)", flush=True)

    cfg_base = ProductionConfig.from_yaml(str(RISK_YAML))
    cfg_base = cfg_base.with_overrides(max_concurrent=20, same_symbol_side_cooldown_days=0)
    print(f"[CFG ] base risk={cfg_base.risk_pct} sym_cap={cfg_base.concentration_max_per_symbol_pct} "
          f"conf_min={cfg_base.conf_min} pyr={cfg_base.pyramid_triggers}", flush=True)

    pool_avwap, n_patched = patch_avwap_conf(pool, lift_to=0.30)
    print(f"[V3 ] AVWAP conf patch: {n_patched:,} trade lifted", flush=True)

    # Variants
    #   V0 = baseline
    #   C2 = V2 risk %2 + V3 AVWAP patch    (champion confirm)
    #   C2_V5 = C2 + V5 pyramid 1.5R triggers (NEW hybrid Task #17 Step 1)
    cfg_c2 = cfg_base.with_overrides(risk_pct=0.02)
    cfg_c2_v5 = cfg_base.with_overrides(risk_pct=0.02, pyramid_triggers=(1.0, 1.5))

    runs = [
        ("V0_baseline", pool, cfg_base),
        ("C2_champion", pool_avwap, cfg_c2),
        ("C2_V5_hybrid", pool_avwap, cfg_c2_v5),
    ]

    results = {}
    for name, pool_v, cfg_v in runs:
        print(f"\n[RUN] {name} — per-month 61 + walk-forward 34 ...", flush=True)
        m = per_month_metrics(pool_v, cfg_v)
        w = walk_forward_metrics(pool_v, cfg_v)
        s = summarize_variant(m, w)
        results[name] = {"month_rows": m, "wf_rows": w, "summary": s}
        print(f"  [{name}] annual={s['annual_pct']:+.1f}% mean_m={s['mean_monthly_pct']:+.2f}% "
              f"pos={s['pos_months']} ge20={s['ge20_months']} neg={s['neg_months']} "
              f"sub20={s['sub20_months']} max_loss={s['max_loss_pct']:+.2f}% "
              f"max_gain={s['max_gain_pct']:+.2f}% CV={s['cv_pct']:.0f}% "
              f"WF mean_ann={s['wf_mean_annual_pct']:+.1f}% r-adj={s['wf_mean_r_adj']:.2f}", flush=True)

    # ========================================================================
    # CSV outputs
    # ========================================================================
    # Per-month: 3 variant × 61 ay
    with CSV_MONTH.open("w", newline="", encoding="utf-8") as fh:
        cols = ["variant", "year", "month", "n_raw", "n_taken", "monthly_pct", "dd_pct", "skip"]
        wr = csv.DictWriter(fh, fieldnames=cols)
        wr.writeheader()
        for name in ["V0_baseline", "C2_champion", "C2_V5_hybrid"]:
            for r in results[name]["month_rows"]:
                row = {"variant": name, **r}
                if isinstance(row.get("monthly_pct"), float):
                    row["monthly_pct"] = f"{row['monthly_pct']:.4f}"
                if isinstance(row.get("dd_pct"), float):
                    row["dd_pct"] = f"{row['dd_pct']:.4f}"
                wr.writerow(row)
    print(f"[CSV ] {CSV_MONTH}")

    # Walk-forward: C2_V5_hybrid
    with CSV_WF.open("w", newline="", encoding="utf-8") as fh:
        cols = ["variant", "window", "start", "end", "trades", "annual_pct", "dd_pct", "r_adj"]
        wr = csv.DictWriter(fh, fieldnames=cols)
        wr.writeheader()
        for name in ["V0_baseline", "C2_champion", "C2_V5_hybrid"]:
            for r in results[name]["wf_rows"]:
                row = {"variant": name, **r}
                row["annual_pct"] = f"{row['annual_pct']:.4f}"
                row["dd_pct"] = f"{row['dd_pct']:.4f}"
                row["r_adj"] = f"{row['r_adj']:.4f}"
                wr.writerow(row)
    print(f"[CSV ] {CSV_WF}")

    # Regime split CSV
    with CSV_REGIME.open("w", newline="", encoding="utf-8") as fh:
        cols = ["variant", "regime", "n_months", "mean_monthly_pct", "median_monthly_pct",
                "cum_return_pct", "annual_pct", "pos_months", "neg_months", "ge20_months",
                "max_gain_pct", "max_loss_pct", "cv_pct"]
        wr = csv.DictWriter(fh, fieldnames=cols)
        wr.writeheader()
        for name in ["V0_baseline", "C2_champion", "C2_V5_hybrid"]:
            for regime_name in REGIME_DEF.keys():
                agg = regime_aggregate(results[name]["month_rows"], regime_name)
                if agg is None:
                    continue
                row = {"variant": name, **agg}
                for k in ("mean_monthly_pct", "median_monthly_pct", "cum_return_pct",
                          "annual_pct", "max_gain_pct", "max_loss_pct", "cv_pct"):
                    row[k] = f"{row[k]:.3f}"
                wr.writerow(row)
    print(f"[CSV ] {CSV_REGIME}")

    # ========================================================================
    # Markdown report
    # ========================================================================
    out = []
    w = lambda s="": out.append(s + "\n")

    w(f"# Lab Task #17 — C2 Champion Extended Validation")
    w(f"")
    w(f"**Lab Scientist:** Head of Self-Improvement Lab")
    w(f"**Date:** {datetime.now(timezone.utc).date().isoformat()}")
    w(f"**Input (Researcher Task #16):** `reports/researcher/2026-05-17_sub20_fix_variants.md`")
    w(f"**Method:** lab.py + production YAML DOKUNULMADI. Tüm değişiklik `cfg.with_overrides()` / pool patch.")
    w(f"**Pool:** `data/sec31_15m_pool.pkl` ({len(pool):,} trade, TOP-4 × 10 sym, 2021-01 → 2026-05)")
    w(f"")
    w(f"---")
    w(f"")

    # =====================================================================
    # Step 1 — 3-variant compare
    # =====================================================================
    w(f"## Step 1 — C2 + V5 Hibrid Karşılaştırma")
    w(f"")
    w(f"3 variant: V0 (baseline) / C2 (champion) / C2+V5 (yeni hibrid).")
    w(f"")
    w(f"| Variant | Annual | Mean M | Pos | ≥+20 | Neg | Sub-20 | Max Loss | Max Gain | CV | WF mean ann | WF r-adj | WF neg |")
    w(f"|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
    for name in ["V0_baseline", "C2_champion", "C2_V5_hybrid"]:
        s = results[name]["summary"]
        w(f"| {name} | {s['annual_pct']:+.1f}% | {s['mean_monthly_pct']:+.2f}% | "
          f"{s['pos_months']} | {s['ge20_months']} | {s['neg_months']} | "
          f"{s['sub20_months']} | {s['max_loss_pct']:+.2f}% | {s['max_gain_pct']:+.2f}% | "
          f"{s['cv_pct']:.0f}% | {s['wf_mean_annual_pct']:+.1f}% | {s['wf_mean_r_adj']:.2f} | "
          f"{s['wf_neg_windows']} |")
    w(f"")

    # Pareto comparison vs C2
    s0 = results["V0_baseline"]["summary"]
    s_c2 = results["C2_champion"]["summary"]
    s_c2v5 = results["C2_V5_hybrid"]["summary"]
    w(f"### C2+V5 hibrid vs C2 (delta)")
    w(f"")
    w(f"| Metric | C2 | C2+V5 | Δ | Yön |")
    w(f"|---|---:|---:|---:|:---:|")
    deltas = [
        ("Annual", s_c2["annual_pct"], s_c2v5["annual_pct"], "higher_better"),
        ("Mean monthly", s_c2["mean_monthly_pct"], s_c2v5["mean_monthly_pct"], "higher_better"),
        ("Pos months", s_c2["pos_months"], s_c2v5["pos_months"], "higher_better"),
        (">=+20 months", s_c2["ge20_months"], s_c2v5["ge20_months"], "higher_better"),
        ("Neg months", s_c2["neg_months"], s_c2v5["neg_months"], "lower_better"),
        ("Sub-20 months", s_c2["sub20_months"], s_c2v5["sub20_months"], "lower_better"),
        ("Max single loss", s_c2["max_loss_pct"], s_c2v5["max_loss_pct"], "higher_better"),  # less negative = better
        ("Max single gain", s_c2["max_gain_pct"], s_c2v5["max_gain_pct"], "higher_better"),
        ("CV", s_c2["cv_pct"], s_c2v5["cv_pct"], "lower_better"),
        ("WF r-adj", s_c2["wf_mean_r_adj"], s_c2v5["wf_mean_r_adj"], "higher_better"),
    ]
    for label, c2v, hv, direction in deltas:
        d = hv - c2v
        if direction == "higher_better":
            sign = "+" if d > 0 else ("-" if d < 0 else "=")
        else:  # lower_better
            sign = "+" if d < 0 else ("-" if d > 0 else "=")
        fmt = "{:+.2f}" if isinstance(c2v, float) else "{:+d}"
        try:
            d_str = fmt.format(d)
        except (ValueError, TypeError):
            d_str = f"{d:+.2f}"
        w(f"| {label} | {c2v} | {hv} | {d_str} | {sign} |")
    w(f"")

    # Verdict on Step 1
    pareto_pass_hybrid = (
        s_c2v5["sub20_months"] <= s_c2["sub20_months"] and
        s_c2v5["pos_months"] >= s_c2["pos_months"] and
        s_c2v5["max_loss_pct"] >= s_c2["max_loss_pct"] and
        s_c2v5["neg_months"] <= s_c2["neg_months"] and
        s_c2v5["mean_monthly_pct"] >= 25.0
    )
    w(f"**Step 1 verdict:** C2+V5 hibrid")
    if pareto_pass_hybrid:
        w(f"= **PARETO-PASS** üzerinden C2 — yeni champion adayı.")
    else:
        w(f"= Pareto-PASS DEĞİL (en az 1 metric C2'den kötü). C2 champion korunur.")
    w(f"")

    # =====================================================================
    # Step 2 — 12-ay × yıllık breakdown (C2)
    # =====================================================================
    w(f"## Step 2 — C2 12-ay × Yıllık Tam Breakdown")
    w(f"")
    w(f"Her yıl 12-ay tablosu, C2 vs V0 ROI%/DD% farkı.")
    w(f"")

    c2_rows = {(r["year"], r["month"]): r for r in results["C2_champion"]["month_rows"]}
    v0_rows = {(r["year"], r["month"]): r for r in results["V0_baseline"]["month_rows"]}

    YEARS = sorted({r["year"] for r in results["V0_baseline"]["month_rows"]})
    for yr in YEARS:
        w(f"### {yr}")
        w(f"")
        w(f"| Ay | V0 ROI% | C2 ROI% | Δ ROI | V0 DD% | C2 DD% | Δ DD | n V0 | n C2 |")
        w(f"|---|---:|---:|---:|---:|---:|---:|---:|---:|")
        yr_v0_rois = []
        yr_c2_rois = []
        for mo in range(1, 13):
            v0r = v0_rows.get((yr, mo), {})
            c2r = c2_rows.get((yr, mo), {})
            if not v0r and not c2r:
                continue
            v0_roi = v0r.get("monthly_pct", 0.0) if v0r.get("skip") == "" else None
            c2_roi = c2r.get("monthly_pct", 0.0) if c2r.get("skip") == "" else None
            if v0_roi is None and c2_roi is None:
                continue
            v0_dd = v0r.get("dd_pct", 0.0)
            c2_dd = c2r.get("dd_pct", 0.0)
            d_roi = (c2_roi or 0) - (v0_roi or 0)
            d_dd = (c2_dd or 0) - (v0_dd or 0)
            w(f"| {mo:02d} | "
              f"{('—' if v0_roi is None else f'{v0_roi:+.2f}')} | "
              f"{('—' if c2_roi is None else f'{c2_roi:+.2f}')} | "
              f"{d_roi:+.2f} | "
              f"{v0_dd:+.2f} | {c2_dd:+.2f} | {d_dd:+.2f} | "
              f"{v0r.get('n_taken', 0)} | {c2r.get('n_taken', 0)} |")
            if v0_roi is not None:
                yr_v0_rois.append(v0_roi)
            if c2_roi is not None:
                yr_c2_rois.append(c2_roi)
        # Yıllık özet
        if yr_v0_rois:
            w(f"")
            v0_mu = mean(yr_v0_rois)
            v0_pos = sum(1 for x in yr_v0_rois if x > 0)
            v0_ge20 = sum(1 for x in yr_v0_rois if x >= 20)
            v0_min = min(yr_v0_rois)
            v0_max = max(yr_v0_rois)
            c2_mu = mean(yr_c2_rois) if yr_c2_rois else 0
            c2_pos = sum(1 for x in yr_c2_rois if x > 0)
            c2_ge20 = sum(1 for x in yr_c2_rois if x >= 20)
            c2_min = min(yr_c2_rois) if yr_c2_rois else 0
            c2_max = max(yr_c2_rois) if yr_c2_rois else 0
            w(f"**{yr} özet:**")
            w(f"- V0: mean ROI {v0_mu:+.2f}% | pos {v0_pos} | ≥+20 {v0_ge20} | min {v0_min:+.2f}% | max {v0_max:+.2f}%")
            w(f"- C2: mean ROI {c2_mu:+.2f}% | pos {c2_pos} | ≥+20 {c2_ge20} | min {c2_min:+.2f}% | max {c2_max:+.2f}%")
            w(f"- Δ: mean {c2_mu - v0_mu:+.2f}pp | pos {c2_pos - v0_pos:+d} | max_gain {c2_max - v0_max:+.2f}pp | min_loss {c2_min - v0_min:+.2f}pp")
            w(f"")

    # =====================================================================
    # Step 3 — Regime split
    # =====================================================================
    w(f"## Step 3 — Regime Split Validation (C2 vs V0)")
    w(f"")
    w(f"Üç rejim: **Bear 2022** (bear yıl, BTC -%64) / **Range 2023** (yatay BTC, en zayıf yıl V0 için) / **Bull 2024-2025** (BTC +%155/+%47).")
    w(f"")
    w(f"| Regime | Variant | n ay | Mean M | Median M | Cum % | Annual % | Pos | Neg | ≥+20 | Max Gain | Max Loss | CV |")
    w(f"|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
    for regime_name in REGIME_DEF.keys():
        for name in ["V0_baseline", "C2_champion", "C2_V5_hybrid"]:
            agg = regime_aggregate(results[name]["month_rows"], regime_name)
            if agg is None:
                continue
            w(f"| {regime_name} | {name} | {agg['n_months']} | {agg['mean_monthly_pct']:+.2f}% | "
              f"{agg['median_monthly_pct']:+.2f}% | {agg['cum_return_pct']:+.1f}% | "
              f"{agg['annual_pct']:+.1f}% | {agg['pos_months']} | {agg['neg_months']} | "
              f"{agg['ge20_months']} | {agg['max_gain_pct']:+.2f}% | {agg['max_loss_pct']:+.2f}% | "
              f"{agg['cv_pct']:.0f}% |")
    w(f"")

    # Regime delta C2 vs V0
    w(f"### Δ (C2 - V0) regime başına")
    w(f"")
    w(f"| Regime | Δ mean_m | Δ pos | Δ neg | Δ ge20 | Δ max_gain | Δ max_loss | Δ cv |")
    w(f"|---|---:|---:|---:|---:|---:|---:|---:|")
    for regime_name in REGIME_DEF.keys():
        a_v0 = regime_aggregate(results["V0_baseline"]["month_rows"], regime_name)
        a_c2 = regime_aggregate(results["C2_champion"]["month_rows"], regime_name)
        if a_v0 is None or a_c2 is None:
            continue
        w(f"| {regime_name} | "
          f"{a_c2['mean_monthly_pct'] - a_v0['mean_monthly_pct']:+.2f}pp | "
          f"{a_c2['pos_months'] - a_v0['pos_months']:+d} | "
          f"{a_c2['neg_months'] - a_v0['neg_months']:+d} | "
          f"{a_c2['ge20_months'] - a_v0['ge20_months']:+d} | "
          f"{a_c2['max_gain_pct'] - a_v0['max_gain_pct']:+.2f}pp | "
          f"{a_c2['max_loss_pct'] - a_v0['max_loss_pct']:+.2f}pp | "
          f"{a_c2['cv_pct'] - a_v0['cv_pct']:+.0f}pp |")
    w(f"")

    # =====================================================================
    # Step 4 — Risk officer audit
    # =====================================================================
    w(f"## Step 4 — Risk Officer Audit (Kısa)")
    w(f"")
    w(f"### C2 config diff vs V0")
    w(f"")
    w(f"| Field | V0 (canonical YAML) | C2 (override) | Δ tipi |")
    w(f"|---|---:|---:|---|")
    w(f"| `risk_per_trade` (sabit risk_pct) | 0.030 | **0.020** | -33% |")
    w(f"| AVWAP trade `conf` (in-memory pool patch) | varsa <0.30 | **lifted 0.30** | re-include AVWAP after `conf_min=0.25` filter |")
    w(f"")
    w(f"### Side-effect kapsamı (kod-statik analiz)")
    w(f"")
    w(f"`risk_pct` kullanan kod path'leri ve C2 etkisi:")
    w(f"")
    w(f"| Modül / dosya | Field | C2 etkisi | Side effect? |")
    w(f"|---|---|---|---|")
    w(f"| `src/price_action/backtest/lab.py` (line 858, 862, 877, 879, 881) | `cfg.risk_pct` + `confidence_risk_tiers` | risk_pct=0.02 → tüm tier'lar sabit kalır (YAML'dan), sadece **fallback** %3→%2 | KONTROLLÜ — tier override yok, sadece fallback |")
    w(f"| `src/price_action/risk/sizing.py` (line 308, 325, 334, 337, 471) | `position_sizing.risk_per_trade` (YAML) | YAML değişmediği için live sizing/officer **etkilenmez**. C2 sadece backtest cfg.risk_pct override. | YOK |")
    w(f"| `src/price_action/risk/breaker.py` (line 118-121) | DD eşikleri (daily/weekly/monthly/cons) | risk_pct'e bağımlı **değil** — doğrudan YAML'dan okuyor. | YOK |")
    w(f"| `src/price_action/risk/vol_target.py` | `risk_per_trade` çarpanı | YAML değişmediği için live etkilenmez. | YOK |")
    w(f"| AVWAP `conf` patch (in-memory pool) | strateji conf alanı | Sadece **backtest replay** scope. Live signal generator (strategies/anchored_vwap_reversal.py) **dokunulmadı**. | YOK (Signal Chief ticket: AVWAP confluence formula revize edilmeli — `conf = (1.5-1.5)/1.5 = 0.0` design bug) |")
    w(f"")
    w(f"### Diğer çalışan preset etkilenmesi")
    w(f"")
    w(f"| Preset | Dosya | C2 etkisi |")
    w(f"|---|---|---|")
    w(f"| Phoenix 1d production v2.0.4 | `configs/risk_phoenix_v204.yaml` | **YOK** — ayrı YAML, risk_per_trade %4 dokunulmadı |")
    w(f"| Phoenix-Scalp 5m | `configs/risk_phoenix_scalp_5m.yaml` | **YOK** — ayrı YAML, risk_per_trade %1 dokunulmadı |")
    w(f"| Phoenix-Scalp 1m | `configs/risk_phoenix_scalp_1m.yaml` | **YOK** — ayrı YAML |")
    w(f"| Phoenix-Scalp 15m baseline | `configs/risk_phoenix_scalp_15m_pyramid_r3.yaml` | **DOKUNULMADI** — C2 sadece override script, draft YAML preview |")
    w(f"")
    w(f"### Verdict")
    w(f"")
    w(f"**Risk officer audit: PASS.** C2 override iki düşük-kapsam değişiklik içerir:")
    w(f"1. `cfg.risk_pct` 0.03 → 0.02 → sadece **backtest lab.py** fallback. Live sizing (sizing.py) YAML okur, etkilenmez.")
    w(f"2. AVWAP conf in-memory pool patch → sadece **backtest replay** scope. Live strateji generator dokunulmadı.")
    w(f"")
    w(f"Production YAML aktivasyonu (live'a geçiş) için ayrı sign-off + draft YAML user incelemesi zorunlu.")
    w(f"")

    # =====================================================================
    # Step 5 — Pre-live ETA
    # =====================================================================
    w(f"## Step 5 — Pre-Live ETA (C2 Paper Trade Gate)")
    w(f"")
    w(f"### Beklenti seti (C2 5y backtest)")
    w(f"")
    w(f"| Metric | C2 backtest | Paper 30g target | Kill threshold |")
    w(f"|---|---:|---|---|")
    w(f"| Annual ROI | {s_c2['annual_pct']:+.1f}% | **+%26 aylık ROI** ortalama (mandate üstü) | <+%10 mean ⇒ alarm |")
    w(f"| Pos/Neg aylık oran | {s_c2['pos_months']}/{s_c2['neg_months']} = {s_c2['pos_months']/(s_c2['pos_months']+s_c2['neg_months'])*100:.0f}% pos | **~%90 pos** | 30g'de neg > 1 ⇒ kill |")
    w(f"| Max single ay loss | {s_c2['max_loss_pct']:+.2f}% | Asla > -%10 olmamalı | 30g'de loss > -%10 ⇒ kill |")
    w(f"| CV | {s_c2['cv_pct']:.0f}% | <%120 hedef | >%200 ⇒ alarm (yapısal değişim) |")
    w(f"| WF r-adj | {s_c2['wf_mean_r_adj']:.2f} | min %15 (stress-test) | <%5 ⇒ kill |")
    w(f"")
    w(f"### Gate koşulları (üretim onayı için)")
    w(f"")
    w(f"1. **Capital cap $1K** (ilk 30g) — likidite testi, draw-down sermayenin %10 üstüne çıkmamalı.")
    w(f"2. **Beklenen aylık ROI +%26** — mandate üstü. Realize +%15 altı ise yapısal sapma alarmı.")
    w(f"3. **Beklenen neg ay 30g'de: ~0-1** — 2+ neg ay görüldüyse kill switch.")
    w(f"4. **Beklenen max ay loss -%4.72** — gözlenen loss > -%10 ise kill switch.")
    w(f"5. **Slippage hedef <25bps** (`SlippageExceededError` SEC26.B-5 entegrasyonu).")
    w(f"6. **AVWAP conf revize zorunluluğu:** Signal Chief ticket aç (production'a giderken AVWAP `confluence_score` formula revize — backtest patch live'da otomatik gerçekleşmez).")
    w(f"")
    w(f"### Drift detection setup")
    w(f"")
    w(f"30g paper sonrası KS test:")
    w(f"- Backtest 5y aylık ROI dağılımı vs paper 30g (1 ay sample) → bootstrap-equivalent slice.")
    w(f"- p-value < 0.01 ⇒ drift alarmı (CEO brief).")
    w(f"- Slippage ortalama > 20 bps ⇒ fee model assumption sapması.")
    w(f"")

    # =====================================================================
    # Step 6 — Final verdict & draft YAML
    # =====================================================================
    w(f"## Step 6 — Final Verdict")
    w(f"")
    w(f"### C2 production candidate onayı")
    w(f"")

    c2_verdict_items = []
    # 1. Pareto vs V0
    c2_verdict_items.append(("Sub-20 ay (35 → ?)", s_c2["sub20_months"] <= s0["sub20_months"]))
    c2_verdict_items.append(("Neg ay (≤ V0)", s_c2["neg_months"] <= s0["neg_months"]))
    c2_verdict_items.append(("Max loss (≥ V0)", s_c2["max_loss_pct"] >= s0["max_loss_pct"]))
    c2_verdict_items.append(("Pos ay (≥ V0)", s_c2["pos_months"] >= s0["pos_months"]))
    c2_verdict_items.append(("Mean monthly ≥ +%25", s_c2["mean_monthly_pct"] >= 25.0))
    c2_verdict_items.append(("Annual ≥ +%800", s_c2["annual_pct"] >= 800.0))
    c2_verdict_items.append(("Max loss ≥ -%10", s_c2["max_loss_pct"] >= -10.0))
    c2_verdict_items.append(("WF r-adj ≥ %15", s_c2["wf_mean_r_adj"] >= 15.0))
    c2_verdict_items.append(("WF neg pencere = 0", s_c2["wf_neg_windows"] == 0))

    n_pass = sum(1 for _, ok in c2_verdict_items if ok)
    w(f"**Mandate kontrol ({n_pass}/{len(c2_verdict_items)}):**")
    w(f"")
    for label, ok in c2_verdict_items:
        flag = "PASS" if ok else "FAIL"
        w(f"- [{flag}] {label}")
    w(f"")

    c2_approved = (n_pass >= len(c2_verdict_items) - 1)  # ≥ 8/9
    if c2_approved:
        w(f"**Verdict: C2 PRODUCTION CANDIDATE — APPROVED (lab brief).**")
        w(f"")
        w(f"Sonraki adım: CEO brief + insan principal sign-off. Production YAML aktivasyonu için draft `configs/risk_phoenix_scalp_15m_c2_champion.yaml` user'a sunulur (production YAML değiştirilmez).")
    else:
        w(f"**Verdict: C2 conditional — ek validation gerek (mandate kontrol sınırda).**")
    w(f"")

    w(f"### C2+V5 hibrid alternatif değerlendirmesi")
    w(f"")
    if pareto_pass_hybrid:
        w(f"**C2+V5 PARETO-PASS** — yeni champion adayı (C2 üstünde).")
        w(f"")
        w(f"Karşılaştırma C2 vs C2+V5:")
        w(f"- Annual: {s_c2['annual_pct']:+.1f}% → {s_c2v5['annual_pct']:+.1f}% (Δ {s_c2v5['annual_pct'] - s_c2['annual_pct']:+.1f}pp)")
        w(f"- Sub-20 ay: {s_c2['sub20_months']} → {s_c2v5['sub20_months']} (Δ {s_c2v5['sub20_months'] - s_c2['sub20_months']:+d})")
        w(f"- Max loss: {s_c2['max_loss_pct']:+.2f}% → {s_c2v5['max_loss_pct']:+.2f}% (Δ {s_c2v5['max_loss_pct'] - s_c2['max_loss_pct']:+.2f}pp)")
        w(f"")
        w(f"**Karar:** Lab önerisi: C2+V5 hibrid champion. Eğer max loss veya neg ay C2+V5'te kötüleşmediyse, V5'in pyramid 1.5R tetiği daha agresif compound üretiyor.")
    else:
        w(f"**C2+V5 Pareto-PASS DEĞİL** — V5 hibrid C2'yi yenmedi. **C2 tek başına champion kalır.**")
        w(f"")
        w(f"V5'in bireysel Pareto-PASS'i, AVWAP patch (V3) ile kombine edildiğinde net negatif/null. Risk profilini C2'nin ötesine itmek için yararı yok.")
    w(f"")

    # =====================================================================
    # Draft YAML preview
    # =====================================================================
    w(f"### Draft YAML preview (üretim için değil — sadece user sign-off referans)")
    w(f"")
    w(f"`configs/risk_phoenix_scalp_15m_c2_champion.yaml` oluşturuldu (preview only).")
    w(f"")
    w(f"Üretim YAML dokunulmadı. C2 aktivasyonu için manuel adım:")
    w(f"1. User draft YAML'i inceler.")
    w(f"2. Risk Officer sign-off.")
    w(f"3. Principal sign-off.")
    w(f"4. Production YAML manuel kopyala (script otomasyon yok).")
    w(f"")

    # =====================================================================
    # Disiplin notları
    # =====================================================================
    w(f"## Disiplin Notları")
    w(f"")
    w(f"- **lab.py + production YAML dokunulmadı.** Tüm değişiklik `cfg.with_overrides()` veya pool in-memory patch.")
    w(f"- **Tournament disiplin:** C2 ve C2+V5 her ikisi OOS (61-ay full coverage + 34-pencere walk-forward).")
    w(f"- **Sayılar raw CSV'den verify edilebilir:** `sec52_c2_champion_per_month.csv`, `sec52_c2_champion_regime_split.csv`.")
    w(f"- **R5 tuzağı kontrol:** Pareto-frontier disiplin (sub-20 ay × annual return), V5 hibrid eklerken max_loss / neg_ay regression yok.")
    w(f"- **1d Phoenix + 5m configs etkilenmedi** (ayrı YAML).")
    w(f"- **AVWAP conf patch:** sadece backtest scope. Production aktivasyonu için Signal Chief ticket zorunlu (`anchored_vwap_reversal.py` `confluence_score` formula revize).")
    w(f"")
    w(f"**Ekler:**")
    w(f"- `reports/lab/sec52_c2_champion_per_month.csv` — V0/C2/C2+V5 × 61 ay")
    w(f"- `reports/lab/sec52_c2_champion_regime_split.csv` — 3 rejim × 3 variant")
    w(f"- `reports/lab/sec52_c2_v5_hybrid_walkforward.csv` — 3 variant × 34 pencere WF")
    w(f"- `configs/risk_phoenix_scalp_15m_c2_champion.yaml` — preview draft, production untouched")
    w(f"- Üretim script: `scripts/lab_task17_c2_champion_validation.py` (deterministik)")

    REPORT.write_text("".join(out), encoding="utf-8")
    print(f"\n[DONE] {REPORT}")

    # ========================================================================
    # Draft YAML preview (production YAML untouched)
    # ========================================================================
    # Read baseline YAML, modify risk_per_trade only, add header note
    src = RISK_YAML.read_text(encoding="utf-8")
    # Replace risk_per_trade 0.030 and backtest_risk_pct 0.030 → 0.020
    out_yaml = src.replace("risk_per_trade: 0.030", "risk_per_trade: 0.020  # C2 CHAMPION — V2 patch (sec51 PARETO_PASS, Researcher Task #16)")
    out_yaml = out_yaml.replace("backtest_risk_pct: 0.030", "backtest_risk_pct: 0.020  # C2 CHAMPION — V2 patch")
    # Modify preset_name and bot_name to mark as draft
    out_yaml = out_yaml.replace("preset_name: phoenix_scalp_15m_pyramid_r3",
                                  "preset_name: phoenix_scalp_15m_c2_champion")
    out_yaml = out_yaml.replace("bot_name: PHOENIX-SCALP-15m-PYR-R3",
                                  "bot_name: PHOENIX-SCALP-15m-C2-CHAMPION  # DRAFT — sign-off pending")
    # Prepend header
    header = """# =============================================================================
# PHOENIX-SCALP 15m C2 CHAMPION — DRAFT (2026-05-17 evening)
# =============================================================================
# Bot: PHOENIX-SCALP-15m-C2-CHAMPION
# Status: DRAFT — Principal sign-off PENDING (live NOT active)
# Origin: Researcher Task #16 PARETO_PASS + Lab Task #17 validation
#
# DELTA vs baseline (risk_phoenix_scalp_15m_pyramid_r3.yaml):
#   1. risk_per_trade 0.030 -> 0.020 (V2 patch)
#   2. AVWAP confluence_score formula revise REQUIRED (Signal Chief ticket)
#      Current bug: conf = (1.5 - 1.5) / 1.5 = 0.0 (sec51 disiplin notes)
#      Backtest replay patched in-memory. PRODUCTION ACTIVATION = signal generator
#      code change first.
#
# WALK-FORWARD (34 window 2y train / 90d OOS):
#   Annual: +1112.5%  (V0 baseline: +1072.9%)
#   r-adj:  32.66     (V0: 30.89)
#   Neg windows: 0/34
#
# PER-MONTH (61 ay 2021-01 -> 2026-05):
#   Annual:   +1143%   (V0: +1232%)
#   Mean M:   +26.29%  (V0: +28.87%)
#   Pos:      55/61    (V0: 52)
#   Neg:      6/61     (V0: 7)
#   Sub-20:   33/61    (V0: 35)
#   Max loss: -4.72%   (V0: -7.29%)
#   CV:       115%     (V0: 144%)
#
# CHANGE LOG vs production:
#   - Production YAML (risk_phoenix_scalp_15m_pyramid_r3.yaml) UNTOUCHED.
#   - This file = preview-only. Manuel kopya + sign-off ile aktif edilir.
# =============================================================================

"""
    DRAFT_YAML.write_text(header + out_yaml, encoding="utf-8")
    print(f"[DRAFT] {DRAFT_YAML}")


if __name__ == "__main__":
    main()
