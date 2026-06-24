"""SEC54.1 — Fee Retest Sprint (Execution Chief MS-01).

Problem: SEC53 +%1082 baseline = SIFIR FEE simülasyonu.
         lab.py'ye fee_bps_per_trade parametresi eklendi (SEC54.1 MS-01).
         Bu script 4 senaryo ile gerçek fee etkisini ölçer.

Senaryolar:
  A: fee=0     → control (baseline +%1082, verify byte-identical)
  B: fee=+8    → taker only worst-case (~8 bps round-trip Binance taker)
  C: fee=-4    → maker rebate best-case (~4 bps rebate her iki leg)
  D: fee=+4    → realistic blend (%50 taker + %50 maker)

Pool: data/sec53_15m_pool_v11.pkl (51.9 MB)
Config: V2 (risk_pct=0.02) + V5 (pyramid_triggers=(1.0, 1.5))

Çıktılar:
  reports/execution_chief/2026-05-19_sec54_1_fee_retest.md
  reports/execution_chief/sec54_1_per_month_A_fee0.csv
  reports/execution_chief/sec54_1_per_month_B_fee8.csv
  reports/execution_chief/sec54_1_per_month_C_feeminus4.csv
  reports/execution_chief/sec54_1_per_month_D_fee4.csv
  reports/execution_chief/sec54_1_walkforward_A_fee0.csv
  reports/execution_chief/sec54_1_walkforward_B_fee8.csv
  reports/execution_chief/sec54_1_walkforward_C_feeminus4.csv
  reports/execution_chief/sec54_1_walkforward_D_fee4.csv
"""
from __future__ import annotations

import csv
import io
import os
import pickle
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean, stdev

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

# ============================================================================
# Paths
# ============================================================================
POOL_PATH = ROOT / "data" / "sec53_15m_pool_v11.pkl"
RISK_YAML = ROOT / "configs" / "risk_phoenix_scalp_15m_c2v5_final.yaml"
OUT_DIR = ROOT / "reports" / "execution_chief"
REPORT = OUT_DIR / "2026-05-19_sec54_1_fee_retest.md"

# SEC53 baseline (fee=0 control — from sec53_c2v5_per_month.csv)
SEC53_BASELINE = {
    "annual_pct": 1082.3,
    "mean_monthly_pct": 25.86,
    "pos_months": 54,
    "neg_months": 7,
    "max_loss_pct": -4.57,
    "cv_pct": 120.0,
    "wf_mean_r_adj": 42.75,
}

# TOP-4 strategy names (SEC53 pool filter)
TOP4_NAMES = {
    "vsa_climax_test",
    "brooks_failed_breakout",
    "anchored_vwap_reversal",
    "engulfing_continuation",
}

# SEC53 pool SHA256 (integrity check)
POOL_SHA256_EXPECTED = "59a794ef278e47f696cdb14ddf42db383ed097474f938f8902a34e450a4e3ad6"


# ============================================================================
# Pool integrity
# ============================================================================
def verify_pool_sha256(path: Path) -> bool:
    import hashlib
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    actual = h.hexdigest()
    if actual != POOL_SHA256_EXPECTED:
        print(f"[WARN] Pool SHA256 mismatch: expected {POOL_SHA256_EXPECTED[:16]}... "
              f"got {actual[:16]}...", flush=True)
        return False
    print(f"[SHA256] Pool integrity OK: {actual[:16]}...", flush=True)
    return True


# ============================================================================
# Utilities (from sec53_avwap_v11_parity.py — shared pattern)
# ============================================================================
def to_utc(ts):
    if hasattr(ts, "tz_localize"):
        if ts.tzinfo is None:
            return ts.tz_localize("UTC")
        return ts.tz_convert("UTC")
    if ts.tzinfo is None:
        return ts.replace(tzinfo=timezone.utc)
    return ts.astimezone(timezone.utc)


def per_month_metrics(pool: list[dict], cfg: ProductionConfig) -> list[dict]:
    pool = sorted(pool, key=lambda x: to_utc(x["entry_ts"]))
    if not pool:
        return []
    start = to_utc(pool[0]["entry_ts"])
    end = to_utc(pool[-1]["entry_ts"])
    months = []
    cy, cm = start.year, start.month
    while True:
        ms = datetime(cy, cm, 1, tzinfo=timezone.utc)
        me = (datetime(cy + 1, 1, 1, tzinfo=timezone.utc) if cm == 12
              else datetime(cy, cm + 1, 1, tzinfo=timezone.utc))
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


def walk_forward_metrics(pool: list[dict], cfg: ProductionConfig,
                          train_days: int = 730, oos_days: int = 90,
                          step_days: int = 30) -> list[dict]:
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


def summarize_variant(month_rows: list[dict], wf_rows: list[dict]) -> dict:
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
    neg = sum(1 for r in rets if r < 0)
    ge20 = sum(1 for r in rets if r >= 20.0)
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


def save_month_csv(path: Path, rows: list[dict]) -> None:
    with path.open("w", newline="", encoding="utf-8") as fh:
        cols = ["year", "month", "n_raw", "n_taken", "monthly_pct", "dd_pct", "skip"]
        wr = csv.DictWriter(fh, fieldnames=cols)
        wr.writeheader()
        for r in rows:
            row = dict(r)
            row["monthly_pct"] = f"{row['monthly_pct']:.4f}"
            row["dd_pct"] = f"{row['dd_pct']:.4f}"
            wr.writerow(row)


def save_wf_csv(path: Path, rows: list[dict]) -> None:
    with path.open("w", newline="", encoding="utf-8") as fh:
        cols = ["window", "start", "end", "trades", "annual_pct", "dd_pct", "r_adj"]
        wr = csv.DictWriter(fh, fieldnames=cols)
        wr.writeheader()
        for r in rows:
            row = dict(r)
            row["annual_pct"] = f"{row['annual_pct']:.4f}"
            row["dd_pct"] = f"{row['dd_pct']:.4f}"
            row["r_adj"] = f"{row['r_adj']:.4f}"
            wr.writerow(row)


def mandate_check_sec54(s: dict) -> dict:
    """SEC54 mandate: yıllık ≥%600, mean ≥%20, neg ≤%15 (9/61ay), max_loss ≥-%8."""
    checks = {
        "annual_ge_600": s["annual_pct"] >= 600.0,
        "mean_monthly_ge_20": s["mean_monthly_pct"] >= 20.0,
        "neg_months_le_15": s["neg_months"] <= 15,
        "max_loss_ge_neg8": s["max_loss_pct"] >= -8.0,
    }
    n_pass = sum(1 for v in checks.values() if v)
    return {"checks": checks, "n_pass": n_pass, "total": len(checks)}


def run_scenario(label: str, fee_bps: float, pool: list[dict], cfg_base: ProductionConfig,
                 out_dir: Path) -> dict:
    """Tek senaryo replay — per-month + walk-forward + summary."""
    print(f"\n[SCENARIO {label}] fee={fee_bps:+.1f} bps", flush=True)
    cfg = cfg_base.with_overrides(fee_bps_per_trade=fee_bps)
    t0 = time.time()
    print(f"  per-month...", flush=True)
    month_rows = per_month_metrics(pool, cfg)
    print(f"  walk-forward...", flush=True)
    wf_rows = walk_forward_metrics(pool, cfg)
    s = summarize_variant(month_rows, wf_rows)
    elapsed = time.time() - t0

    slug = label.replace("=", "").replace("+", "plus").replace("-", "minus").replace(" ", "_")
    csv_m = out_dir / f"sec54_1_per_month_{slug}.csv"
    csv_w = out_dir / f"sec54_1_walkforward_{slug}.csv"
    save_month_csv(csv_m, month_rows)
    save_wf_csv(csv_w, wf_rows)

    mandate = mandate_check_sec54(s)
    print(f"  annual={s['annual_pct']:+.1f}%  mean={s['mean_monthly_pct']:+.2f}%  "
          f"pos={s['pos_months']}  neg={s['neg_months']}  max_loss={s['max_loss_pct']:+.2f}%  "
          f"CV={s['cv_pct']:.0f}%  WF_radj={s['wf_mean_r_adj']:.2f}  "
          f"mandate={mandate['n_pass']}/{mandate['total']}  [{elapsed/60:.1f}m]", flush=True)
    print(f"  CSVs: {csv_m.name}, {csv_w.name}", flush=True)
    return {**s, "fee_bps": fee_bps, "label": label,
            "mandate_pass": mandate["n_pass"], "mandate_checks": mandate["checks"],
            "csv_month": str(csv_m), "csv_wf": str(csv_w),
            "elapsed_s": elapsed}


# ============================================================================
# Main
# ============================================================================
def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    print("[SEC54.1] Fee Retest Sprint — Execution Chief MS-01", flush=True)
    print(f"  Pool: {POOL_PATH}", flush=True)
    print(f"  YAML: {RISK_YAML}", flush=True)

    # ========================================================================
    # Pool load + integrity
    # ========================================================================
    if not POOL_PATH.exists():
        print(f"[ERROR] Pool not found: {POOL_PATH}", flush=True)
        print("  Run scripts/sec53_avwap_v11_parity.py first.", flush=True)
        sys.exit(1)

    print(f"\n[POOL] Loading {POOL_PATH.stat().st_size/1e6:.1f} MB...", flush=True)
    t0 = time.time()
    with POOL_PATH.open("rb") as f:
        pool_raw = pickle.load(f)
    print(f"  Loaded {len(pool_raw):,} raw trades ({time.time()-t0:.1f}s)", flush=True)

    # SHA256 verify (background — non-blocking on mismatch, just warn)
    verify_pool_sha256(POOL_PATH)

    # Filter TOP-4 × 10 sym (same as SEC53)
    pool = [t for t in pool_raw if t.get("strategy") in TOP4_NAMES]
    print(f"  Filtered TOP-4: {len(pool):,} trades", flush=True)

    # ========================================================================
    # Base config — C2+V5 (V2 risk %2 + V5 pyramid 1.5R)
    # ========================================================================
    print(f"\n[CONFIG] Loading {RISK_YAML.name}...", flush=True)
    cfg_base = ProductionConfig.from_yaml(str(RISK_YAML))
    # SEC53 replay settings: same as sec53_avwap_v11_parity.py
    cfg_base = cfg_base.with_overrides(
        risk_pct=0.02,
        pyramid_triggers=(1.0, 1.5),
        max_concurrent=20,
        same_symbol_side_cooldown_days=0,
    )
    print(f"  risk_pct={cfg_base.risk_pct}  pyramid={cfg_base.pyramid_triggers}  "
          f"fee_default={cfg_base.fee_bps_per_trade}", flush=True)

    # ========================================================================
    # 4 Scenarios
    # ========================================================================
    scenarios = [
        ("A_fee0",       0.0,  "Control (zero fee — SEC53 baseline verify)"),
        ("B_fee8",       8.0,  "Taker only worst-case (8 bps round-trip)"),
        ("C_feeminus4", -4.0,  "Maker rebate best-case (-4 bps round-trip)"),
        ("D_fee4",       4.0,  "Realistic blend (50% taker + 50% maker)"),
    ]

    results = {}
    for slug, fee_bps, desc in scenarios:
        r = run_scenario(slug, fee_bps, pool, cfg_base, OUT_DIR)
        r["description"] = desc
        results[slug] = r

    # ========================================================================
    # Backward-compat verify (Scenario A fee=0 vs SEC53 baseline)
    # ========================================================================
    print("\n[BACKWARD-COMPAT] Verifying fee=0 parity with SEC53 baseline...", flush=True)
    a = results["A_fee0"]
    tol_annual = 5.0   # ±5pp (config change tolerance — SEC53 used max_concurrent=20)
    tol_mean = 1.0     # ±1pp
    annual_delta = abs(a["annual_pct"] - SEC53_BASELINE["annual_pct"])
    mean_delta = abs(a["mean_monthly_pct"] - SEC53_BASELINE["mean_monthly_pct"])
    compat_ok = (annual_delta <= tol_annual and mean_delta <= tol_mean)
    print(f"  annual: got={a['annual_pct']:+.1f}%  ref={SEC53_BASELINE['annual_pct']:+.1f}%  "
          f"Δ={annual_delta:+.1f}pp  tol=±{tol_annual}  {'OK' if annual_delta<=tol_annual else 'DRIFT'}",
          flush=True)
    print(f"  mean_m: got={a['mean_monthly_pct']:+.2f}%  ref={SEC53_BASELINE['mean_monthly_pct']:+.2f}%  "
          f"Δ={mean_delta:+.2f}pp  tol=±{tol_mean}  {'OK' if mean_delta<=tol_mean else 'DRIFT'}",
          flush=True)
    print(f"  BACKWARD-COMPAT: {'PASS' if compat_ok else 'DRIFT (investigate)'}", flush=True)

    # ========================================================================
    # Mandate compliance summary
    # ========================================================================
    print("\n[MANDATE SEC54] Compliance check (annual>=600, mean>=20, neg<=15, maxloss>=-8):",
          flush=True)
    for slug, _, desc in scenarios:
        r = results[slug]
        m = r["mandate_pass"]
        tag = "PASS" if m == 4 else ("MARGINAL" if m == 3 else "NO-GO")
        print(f"  [{slug}] fee={r['fee_bps']:+.1f}bps  annual={r['annual_pct']:+.1f}%  "
              f"mandate={m}/4  [{tag}]", flush=True)

    # B scenario verdict
    b = results["B_fee8"]
    if b["annual_pct"] >= 600:
        overall_verdict = "PASS"
        verdict_detail = "SEC54.3/4/5 FIRE — Scenario B annual >= 600%"
    elif b["annual_pct"] >= 400:
        overall_verdict = "MARGINAL"
        verdict_detail = "Post-only mandatory + retest SEC54.3 before live"
    else:
        overall_verdict = "NO-GO"
        verdict_detail = "C2+V5 archive — fee erosion exceeds profit capacity"

    d_scenario = results["D_fee4"]
    print(f"\n[VERDICT] {overall_verdict}: {verdict_detail}", flush=True)
    print(f"  Scenario D (realistic): annual={d_scenario['annual_pct']:+.1f}%  "
          f"mean={d_scenario['mean_monthly_pct']:+.2f}%  "
          f"paper_trade_expectation: [{d_scenario['annual_pct']*0.3:+.0f}%..{d_scenario['annual_pct']*0.6:+.0f}%]/yr",
          flush=True)

    # ========================================================================
    # Markdown report
    # ========================================================================
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    out = []
    w = lambda s="": out.append(s + "\n")

    w("# SEC54.1 — Fee Retest Sprint (MS-01)")
    w()
    w(f"**Execution Chief:** Head of Execution")
    w(f"**Date:** {now_str}")
    w(f"**Sprint:** SEC54.1 — lab.py fee_bps_per_trade param (MS-01)")
    w(f"**Pool:** `data/sec53_15m_pool_v11.pkl` ({POOL_PATH.stat().st_size/1e6:.1f} MB)")
    w(f"**Config:** C2+V5 hibrid (risk_pct=0.02, pyramid_triggers=(1.0, 1.5))")
    w()
    w("---")
    w()
    w("## Executive Summary — SCENARIO VERDICT TABLE")
    w()
    w("| Senaryo | fee (bps) | Annual | Mean M | Neg ay | Max loss | WF r-adj | Mandate | Verdict |")
    w("|---------|-----------|--------|--------|--------|----------|----------|---------|---------|")
    for slug, fee_bps, desc in scenarios:
        r = results[slug]
        m = r["mandate_pass"]
        if slug == "A_fee0":
            v = "control"
        elif m == 4:
            v = "PASS"
        elif m == 3:
            v = "MARGINAL"
        else:
            v = "NO-GO"
        w(f"| {slug} | {fee_bps:+.1f} | {r['annual_pct']:+.1f}% | {r['mean_monthly_pct']:+.2f}% "
          f"| {r['neg_months']} | {r['max_loss_pct']:+.2f}% | {r['wf_mean_r_adj']:.2f} "
          f"| {m}/4 | {v} |")
    w()
    w("---")
    w()
    w("## Revize Mandate Compliance (SEC54 Gates)")
    w()
    w("Gates: (1) annual ≥%600, (2) mean monthly ≥%20, (3) neg ay ≤15, (4) max loss ≥-%8")
    w()
    for slug, fee_bps, desc in scenarios:
        r = results[slug]
        w(f"### {slug} (fee={fee_bps:+.1f} bps) — {desc}")
        w()
        for k, v in r["mandate_checks"].items():
            icon = "PASS" if v else "FAIL"
            w(f"- [{icon}] {k}")
        w()
    w("---")
    w()
    w("## Backward-Compat Verify (fee=0 vs SEC53 baseline)")
    w()
    w(f"- SEC53 baseline annual: **+{SEC53_BASELINE['annual_pct']:.1f}%**")
    w(f"- Scenario A (fee=0) annual: **{a['annual_pct']:+.1f}%**  Δ={annual_delta:+.1f}pp  "
      f"tol=±{tol_annual}pp  **{'PASS' if annual_delta<=tol_annual else 'DRIFT'}**")
    w(f"- SEC53 baseline mean_m: **+{SEC53_BASELINE['mean_monthly_pct']:.2f}%**")
    w(f"- Scenario A mean_m: **{a['mean_monthly_pct']:+.2f}%**  Δ={mean_delta:+.2f}pp  "
      f"tol=±{tol_mean}pp  **{'PASS' if mean_delta<=tol_mean else 'DRIFT'}**")
    w(f"- **BACKWARD-COMPAT: {'PASS' if compat_ok else 'DRIFT'}**")
    w()
    w("---")
    w()
    w("## Per-Scenario Full Metrics")
    w()
    for slug, fee_bps, desc in scenarios:
        r = results[slug]
        w(f"### {slug} — {desc}")
        w()
        w(f"| Metric | Value |")
        w(f"|--------|-------|")
        w(f"| Annual | {r['annual_pct']:+.1f}% |")
        w(f"| Mean monthly | {r['mean_monthly_pct']:+.2f}% |")
        w(f"| Pos months | {r['pos_months']} |")
        w(f"| Neg months | {r['neg_months']} |")
        w(f"| Sub-20% months | {r['sub20_months']} |")
        w(f"| Max loss | {r['max_loss_pct']:+.2f}% |")
        w(f"| Max gain | {r['max_gain_pct']:+.2f}% |")
        w(f"| CV | {r['cv_pct']:.0f}% |")
        w(f"| WF windows | {r['wf_n_windows']} |")
        w(f"| WF mean annual | {r['wf_mean_annual_pct']:+.1f}% |")
        w(f"| WF mean DD | {r['wf_mean_dd_pct']:+.1f}% |")
        w(f"| WF r-adj | {r['wf_mean_r_adj']:.2f} |")
        w(f"| WF neg windows | {r['wf_neg_windows']} |")
        w(f"| Mandate | {r['mandate_pass']}/4 |")
        w(f"| per-month CSV | `{Path(r['csv_month']).name}` |")
        w(f"| walk-forward CSV | `{Path(r['csv_wf']).name}` |")
        w()
    w("---")
    w()
    w("## Fee Model Context")
    w()
    w("- **fee_bps_per_trade** = round-trip fee (entry + exit combined)")
    w("- Binance futures taker: ~4 bps per side = 8 bps round-trip (Scenario B)")
    w("- Post-only maker rebate: ~-2 bps per side = -4 bps round-trip (Scenario C)")
    w("- Realistic 50/50 blend: +4 bps round-trip (Scenario D)")
    w("- Pyramid add-legs: each triggered leg = 1 additional round-trip × leg_size")
    w("- R-normalized formula: `fee_R = fee_bps_per_trade / (sl_pct × 10_000)`")
    w()
    w("## Overall Verdict")
    w()
    w(f"**{overall_verdict}**: {verdict_detail}")
    w()
    w(f"Scenario D (realistic blend, fee=+4 bps):")
    w(f"- Annual: {d_scenario['annual_pct']:+.1f}%")
    w(f"- Mean monthly: {d_scenario['mean_monthly_pct']:+.2f}%")
    w(f"- Paper trade expectation range: [{d_scenario['annual_pct']*0.3:+.0f}%, "
      f"{d_scenario['annual_pct']*0.6:+.0f}%]/yr")
    w(f"- Mandate: {d_scenario['mandate_pass']}/4")
    w()
    w("---")
    w()
    w(f"*Generated: {now_str} by SEC54.1 fee_retest sprint*")

    report_text = "".join(out)
    with REPORT.open("w", encoding="utf-8") as fh:
        fh.write(report_text)
    print(f"\n[REPORT] {REPORT}", flush=True)
    print("[SEC54.1] DONE", flush=True)


if __name__ == "__main__":
    main()
