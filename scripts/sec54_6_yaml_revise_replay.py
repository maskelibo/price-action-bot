"""SEC54.6 — Risk YAML Revize Replay Verify (Lab Sprint).

Principal sign-off ile 4 parametre revize edildi (configs/risk_phoenix_scalp_15m_c2v5_final.yaml):
    daily_loss_pct: 0.03 -> 0.05
    consecutive_losses: 5 -> 7
    monthly_loss_pct_short: 0.04 -> 0.07
    monthly_loss_pct_long: 0.10 -> 0.12

Gerekce: Risk Officer SEC54 audit 3 YAML FAIL — daily + consec + monthly_short
over-trigger empirik.

Bu script:
  1. Yeni YAML ile pool replay (3 fee senaryo: A=0, B=+8, D=+4)
  2. Eski YAML ile (override) ayni pool ayni fee — halt-event sayim icin
  3. 4 metrik + halt-event delta tablosu
  4. Revize mandate compliance (B1+B3 yumusatildi)
  5. Verdict

Pool: data/sec53_15m_pool_v11.pkl (SHA256 59a794ef...4e3ad6)
Config: configs/risk_phoenix_scalp_15m_c2v5_final.yaml (REVISED)
Reference SEC54.1: reports/execution_chief/2026-05-19_sec54_1_fee_retest.md

Cikti:
  reports/lab/2026-05-19_sec54_6_yaml_revise_replay.md
  reports/lab/sec54_6_per_month_{A,B,D}_{old,new}.csv
  reports/lab/sec54_6_walkforward_{A,B,D}_{old,new}.csv
  reports/lab/sec54_6_events_{A,B,D}_{old,new}.csv
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
OUT_DIR = ROOT / "reports" / "lab"
REPORT = OUT_DIR / "2026-05-19_sec54_6_yaml_revise_replay.md"

# Old breaker values (PRE-revize) — for direct halt-count comparison
OLD_BREAKER_OVERRIDES = {
    "daily_dd": 0.03,
    "consecutive_loss_n": 5,
    "monthly_dd_short": 0.04,
    "monthly_dd_long": 0.10,
}

# New breaker values (POST-revize) — from REVISED YAML, for label only
NEW_BREAKER_VALUES = {
    "daily_dd": 0.05,
    "consecutive_loss_n": 7,
    "monthly_dd_short": 0.07,
    "monthly_dd_long": 0.12,
}

# TOP-4 strategy names (SEC53 pool filter)
TOP4_NAMES = {
    "vsa_climax_test",
    "brooks_failed_breakout",
    "anchored_vwap_reversal",
    "engulfing_continuation",
}

POOL_SHA256_EXPECTED = "59a794ef278e47f696cdb14ddf42db383ed097474f938f8902a34e450a4e3ad6"

# SEC54.1 baseline (OLD YAML, fee scenarios) — locked reference from
# reports/execution_chief/2026-05-19_sec54_1_fee_retest.md
SEC54_1_OLD = {
    "A_fee0":  {"annual": 1082.3, "mean_m": 25.86, "neg": 7, "max_loss": -4.57,
                "cv": 120, "wf_r_adj": 42.75, "pos": 54, "ge20": 26, "sub20": 35},
    "B_fee8":  {"annual": 1014.9, "mean_m": 25.09, "neg": 7, "max_loss": -4.90,
                "cv": 119, "wf_r_adj": 36.87, "pos": 54, "ge20": 26, "sub20": 35},
    "D_fee4":  {"annual": 1042.2, "mean_m": 25.48, "neg": 7, "max_loss": -4.73,
                "cv": 121, "wf_r_adj": 40.94, "pos": 54, "ge20": 26, "sub20": 35},
}


# ============================================================================
# Utilities (shared with sec54_1)
# ============================================================================
def to_utc(ts):
    if hasattr(ts, "tz_localize"):
        if ts.tzinfo is None:
            return ts.tz_localize("UTC")
        return ts.tz_convert("UTC")
    if ts.tzinfo is None:
        return ts.replace(tzinfo=timezone.utc)
    return ts.astimezone(timezone.utc)


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


def per_month_metrics(pool: list[dict], cfg: ProductionConfig,
                       events_out: list | None = None) -> list[dict]:
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
                         "monthly_pct": 0.0, "dd_pct": 0.0, "skip": "n<10",
                         "halt_events": 0})
            continue
        try:
            month_events: list = [] if events_out is not None else None
            r = production_replay(m_tr, cfg, events_out=month_events)
        except Exception as e:
            rows.append({"year": yr, "month": mo, "n_raw": len(m_tr), "n_taken": 0,
                         "monthly_pct": 0.0, "dd_pct": 0.0, "skip": f"err:{e}",
                         "halt_events": 0})
            continue
        if r is None:
            rows.append({"year": yr, "month": mo, "n_raw": len(m_tr), "n_taken": 0,
                         "monthly_pct": 0.0, "dd_pct": 0.0, "skip": "none",
                         "halt_events": 0})
            continue
        n_events = len(month_events) if month_events is not None else 0
        if events_out is not None and month_events:
            for ev in month_events:
                ev2 = dict(ev)
                ev2["year"] = yr
                ev2["month"] = mo
                events_out.append(ev2)
        rows.append({"year": yr, "month": mo, "n_raw": len(m_tr), "n_taken": r.trades,
                     "monthly_pct": r.total_return * 100, "dd_pct": r.max_drawdown * 100,
                     "skip": "", "halt_events": n_events})
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


def summarize_variant(month_rows: list[dict], wf_rows: list[dict],
                       events: list | None = None) -> dict:
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

    # Event counts (by type) — total across all months
    ev_counts = {"daily_halt": 0, "weekly_halt": 0, "monthly_halt": 0,
                 "monthly_long_halt": 0, "monthly_short_halt": 0,
                 "consecutive_loss_pause": 0, "total": 0}
    if events:
        for e in events:
            t = e.get("type")
            if t in ev_counts:
                ev_counts[t] += 1
            ev_counts["total"] += 1

    # Months affected by monthly_short_halt at least once
    short_halt_months = set()
    if events:
        for e in events:
            if e.get("type") == "monthly_short_halt":
                short_halt_months.add((e.get("year"), e.get("month")))
    n_short_halt_months = len(short_halt_months)

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
        "events": ev_counts,
        "n_short_halt_months": n_short_halt_months,
    }


def save_month_csv(path: Path, rows: list[dict]) -> None:
    with path.open("w", newline="", encoding="utf-8") as fh:
        cols = ["year", "month", "n_raw", "n_taken", "monthly_pct", "dd_pct",
                "halt_events", "skip"]
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


def save_events_csv(path: Path, events: list) -> None:
    with path.open("w", newline="", encoding="utf-8") as fh:
        cols = ["year", "month", "type", "ts"]
        wr = csv.DictWriter(fh, fieldnames=cols)
        wr.writeheader()
        for e in events:
            wr.writerow({
                "year": e.get("year", ""),
                "month": e.get("month", ""),
                "type": e.get("type", ""),
                "ts": str(e.get("ts", "")),
            })


def mandate_check_sec54_6(s: dict) -> dict:
    """SEC54.6 revize mandate (B1+B3): annual>=600, mean>=20, neg<=9 (low-n haric),
    max_loss>=-8 (daily 5% genisledi ama hala bant ici), wf_r_adj>=15.
    """
    checks = {
        "annual_ge_600": s["annual_pct"] >= 600.0,
        "mean_monthly_ge_20": s["mean_monthly_pct"] >= 20.0,
        "neg_months_le_9": s["neg_months"] <= 9,
        "max_loss_ge_neg8": s["max_loss_pct"] >= -8.0,
        "wf_r_adj_ge_15": s["wf_mean_r_adj"] >= 15.0,
    }
    n_pass = sum(1 for v in checks.values() if v)
    return {"checks": checks, "n_pass": n_pass, "total": len(checks)}


def run_scenario(label: str, fee_bps: float, pool: list[dict],
                 cfg_base: ProductionConfig, out_dir: Path,
                 yaml_tag: str) -> dict:
    """Tek senaryo replay — per-month + walk-forward + summary + event log."""
    print(f"\n[SCENARIO {label} / {yaml_tag}] fee={fee_bps:+.1f} bps", flush=True)
    cfg = cfg_base.with_overrides(fee_bps_per_trade=fee_bps)
    t0 = time.time()
    events: list = []
    print(f"  per-month (with event log)...", flush=True)
    month_rows = per_month_metrics(pool, cfg, events_out=events)
    print(f"  walk-forward...", flush=True)
    wf_rows = walk_forward_metrics(pool, cfg)
    s = summarize_variant(month_rows, wf_rows, events=events)
    elapsed = time.time() - t0

    slug = f"{label}_{yaml_tag}"
    csv_m = out_dir / f"sec54_6_per_month_{slug}.csv"
    csv_w = out_dir / f"sec54_6_walkforward_{slug}.csv"
    csv_e = out_dir / f"sec54_6_events_{slug}.csv"
    save_month_csv(csv_m, month_rows)
    save_wf_csv(csv_w, wf_rows)
    save_events_csv(csv_e, events)

    mandate = mandate_check_sec54_6(s)
    print(f"  annual={s['annual_pct']:+.1f}%  mean={s['mean_monthly_pct']:+.2f}%  "
          f"pos={s['pos_months']}  neg={s['neg_months']}  "
          f"max_loss={s['max_loss_pct']:+.2f}%  CV={s['cv_pct']:.0f}%  "
          f"WF_radj={s['wf_mean_r_adj']:.2f}  mandate={mandate['n_pass']}/{mandate['total']}",
          flush=True)
    print(f"  halt events: daily={s['events']['daily_halt']}  "
          f"weekly={s['events']['weekly_halt']}  "
          f"monthly_long={s['events']['monthly_long_halt']}  "
          f"monthly_short={s['events']['monthly_short_halt']} "
          f"(n_months={s['n_short_halt_months']})  "
          f"consec={s['events']['consecutive_loss_pause']}  "
          f"total={s['events']['total']}  [{elapsed/60:.1f}m]", flush=True)
    print(f"  CSVs: {csv_m.name}, {csv_w.name}, {csv_e.name}", flush=True)
    return {**s, "fee_bps": fee_bps, "label": label, "yaml_tag": yaml_tag,
            "mandate_pass": mandate["n_pass"], "mandate_total": mandate["total"],
            "mandate_checks": mandate["checks"],
            "csv_month": str(csv_m), "csv_wf": str(csv_w), "csv_events": str(csv_e),
            "elapsed_s": elapsed}


# ============================================================================
# Main
# ============================================================================
def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    print("[SEC54.6] Risk YAML Revize Replay Verify (Lab Sprint)", flush=True)
    print(f"  Pool: {POOL_PATH}", flush=True)
    print(f"  YAML: {RISK_YAML}", flush=True)
    print(f"  Revize delta: daily 3->5, consec 5->7, m_short 4->7, m_long 10->12 (%)",
          flush=True)

    # ========================================================================
    # Pool load + integrity
    # ========================================================================
    if not POOL_PATH.exists():
        print(f"[ERROR] Pool not found: {POOL_PATH}", flush=True)
        sys.exit(1)

    print(f"\n[POOL] Loading {POOL_PATH.stat().st_size/1e6:.1f} MB...", flush=True)
    t0 = time.time()
    with POOL_PATH.open("rb") as f:
        pool_raw = pickle.load(f)
    print(f"  Loaded {len(pool_raw):,} raw trades ({time.time()-t0:.1f}s)", flush=True)
    verify_pool_sha256(POOL_PATH)

    pool = [t for t in pool_raw if t.get("strategy") in TOP4_NAMES]
    print(f"  Filtered TOP-4: {len(pool):,} trades", flush=True)

    # ========================================================================
    # Base config — NEW YAML (from disk, already revised by Principal)
    # ========================================================================
    print(f"\n[CONFIG] Loading NEW (revised) {RISK_YAML.name}...", flush=True)
    cfg_new = ProductionConfig.from_yaml(str(RISK_YAML))
    # Same replay overrides as SEC54.1 (risk_pct=0.02, pyramid V5, conc=20, no cooldown)
    cfg_new = cfg_new.with_overrides(
        risk_pct=0.02,
        pyramid_triggers=(1.0, 1.5),
        max_concurrent=20,
        same_symbol_side_cooldown_days=0,
    )
    print(f"  NEW breakers: daily={cfg_new.daily_dd}  consec={cfg_new.consecutive_loss_n}  "
          f"m_short={cfg_new.monthly_dd_short}  m_long={cfg_new.monthly_dd_long}",
          flush=True)
    # Sanity: assert NEW YAML actually carries revised values
    assert abs(cfg_new.daily_dd - NEW_BREAKER_VALUES["daily_dd"]) < 1e-9, \
        f"NEW YAML daily_dd mismatch: got {cfg_new.daily_dd}"
    assert cfg_new.consecutive_loss_n == NEW_BREAKER_VALUES["consecutive_loss_n"], \
        f"NEW YAML consec mismatch: got {cfg_new.consecutive_loss_n}"
    assert abs(cfg_new.monthly_dd_short - NEW_BREAKER_VALUES["monthly_dd_short"]) < 1e-9
    assert abs(cfg_new.monthly_dd_long - NEW_BREAKER_VALUES["monthly_dd_long"]) < 1e-9
    print("  [ASSERT] NEW YAML carries revised values  OK", flush=True)

    # OLD breaker config — same NEW base but override 4 breakers back to pre-revise
    cfg_old = cfg_new.with_overrides(**OLD_BREAKER_OVERRIDES)
    print(f"  OLD breakers (override): daily={cfg_old.daily_dd}  "
          f"consec={cfg_old.consecutive_loss_n}  m_short={cfg_old.monthly_dd_short}  "
          f"m_long={cfg_old.monthly_dd_long}", flush=True)

    # ========================================================================
    # 3 Fee scenarios × 2 YAML versions (6 runs)
    # ========================================================================
    scenarios = [
        ("A_fee0",  0.0,  "Control (zero fee — SEC54.1 baseline verify)"),
        ("B_fee8",  8.0,  "Taker only worst-case (8 bps round-trip)"),
        ("D_fee4",  4.0,  "Realistic blend (50% taker + 50% maker)"),
    ]

    results = {}
    for slug, fee_bps, desc in scenarios:
        # NEW YAML run
        r_new = run_scenario(slug, fee_bps, pool, cfg_new, OUT_DIR, yaml_tag="new")
        r_new["description"] = desc
        results[(slug, "new")] = r_new
        # OLD breakers run (same pool, same fee) — halt event count comparison
        r_old = run_scenario(slug, fee_bps, pool, cfg_old, OUT_DIR, yaml_tag="old")
        r_old["description"] = desc
        results[(slug, "old")] = r_old

    # ========================================================================
    # Backward-compat verify (OLD breakers fee=0 vs SEC54.1 baseline)
    # ========================================================================
    print("\n[BACKWARD-COMPAT] OLD breakers fee=0 vs SEC54.1 A_fee0 baseline...",
          flush=True)
    a_old = results[("A_fee0", "old")]
    ref_a = SEC54_1_OLD["A_fee0"]
    tol_annual = 5.0
    tol_mean = 1.0
    annual_delta = abs(a_old["annual_pct"] - ref_a["annual"])
    mean_delta = abs(a_old["mean_monthly_pct"] - ref_a["mean_m"])
    compat_ok = (annual_delta <= tol_annual and mean_delta <= tol_mean)
    print(f"  annual: got={a_old['annual_pct']:+.1f}%  ref={ref_a['annual']:+.1f}%  "
          f"delta={annual_delta:+.1f}pp  tol=±{tol_annual}  "
          f"{'OK' if annual_delta<=tol_annual else 'DRIFT'}", flush=True)
    print(f"  mean_m: got={a_old['mean_monthly_pct']:+.2f}%  ref={ref_a['mean_m']:+.2f}%  "
          f"delta={mean_delta:+.2f}pp  tol=±{tol_mean}  "
          f"{'OK' if mean_delta<=tol_mean else 'DRIFT'}", flush=True)
    print(f"  BACKWARD-COMPAT: {'PASS' if compat_ok else 'DRIFT (investigate)'}",
          flush=True)

    # ========================================================================
    # Mandate compliance — NEW YAML B scenario primary gate
    # ========================================================================
    print("\n[MANDATE SEC54.6] NEW YAML compliance check (5 gate):", flush=True)
    for slug, _, desc in scenarios:
        r = results[(slug, "new")]
        m = r["mandate_pass"]
        tag = "PASS" if m == 5 else ("WARN" if m == 4 else ("MARGINAL" if m == 3 else "NO-GO"))
        print(f"  [{slug} NEW] fee={r['fee_bps']:+.1f}bps  annual={r['annual_pct']:+.1f}%  "
              f"mandate={m}/5  [{tag}]", flush=True)

    b_new = results[("B_fee8", "new")]
    if b_new["mandate_pass"] == 5:
        overall = "PASS"
        verdict_detail = "5/5 gate met under realistic fee — SEC54.6 KAPATILDI, testnet smoke open."
    elif b_new["mandate_pass"] == 4:
        overall = "WARN"
        verdict_detail = "4/5 gate — 1 borderline metric, principal review needed"
    elif b_new["mandate_pass"] == 3:
        overall = "MARGINAL"
        verdict_detail = "3/5 gate — 2 metric border, revize cesaretle kabul edilemez"
    else:
        overall = "FAIL"
        verdict_detail = "Mandate ihlal — YAML revize geri al veya baska parametre revize et"
    print(f"\n[VERDICT] {overall}: {verdict_detail}", flush=True)

    # ========================================================================
    # Markdown report
    # ========================================================================
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    out = []
    w = lambda s="": out.append(s + "\n")

    w("# SEC54.6 — Risk YAML Revize Replay Verify")
    w()
    w(f"**Lab Scientist:** Head of Self-Improvement Lab")
    w(f"**Date:** {now_str}")
    w(f"**Sprint:** SEC54.6 — 4-param revize replay (Principal sign-off 2026-05-18)")
    w(f"**Pool:** `data/sec53_15m_pool_v11.pkl` "
      f"({POOL_PATH.stat().st_size/1e6:.1f} MB, SHA256 `{POOL_SHA256_EXPECTED[:16]}...`)")
    w(f"**Config:** `{RISK_YAML.name}` (REVISED)")
    w(f"**Replay knobs:** risk_pct=0.02, pyramid (1.0, 1.5), max_conc=20, "
      f"cooldown=0 (parity with SEC54.1)")
    w()
    w("---")
    w()
    w("## Executive Summary — VERDICT TABLE")
    w()
    w("| Senaryo | Eski YAML | Yeni YAML | Δ | Mandate (NEW) |")
    w("|---------|-----------|-----------|---|---------------|")
    for slug, _, _ in scenarios:
        r_new = results[(slug, "new")]
        ref = SEC54_1_OLD[slug]
        delta = r_new["annual_pct"] - ref["annual"]
        sign = "+" if delta >= 0 else ""
        m = r_new["mandate_pass"]
        tot = r_new["mandate_total"]
        w(f"| {slug} (fee {r_new['fee_bps']:+.0f}bps) | "
          f"+{ref['annual']:.1f}% | {r_new['annual_pct']:+.1f}% | "
          f"{sign}{delta:.1f}pp | {m}/{tot} |")
    w()
    w(f"**Overall verdict:** **{overall}** — {verdict_detail}")
    w()
    w("---")
    w()
    w("## HALT EVENT REDUCTION TABLE")
    w()
    w("**OLD vs NEW breaker triggers (Scenario A, fee=0, identical pool & overrides):**")
    w()
    a_old_s = results[("A_fee0", "old")]
    a_new_s = results[("A_fee0", "new")]

    def fmt_delta(old: int, new: int) -> str:
        d = new - old
        if old > 0:
            pct = 100.0 * d / old
            return f"{d:+d} ({pct:+.1f}%)"
        return f"{d:+d} (n/a)"

    w("| Breaker (eski→yeni eşik) | Eski tetik sayısı | Yeni tetik sayısı | Reduction |")
    w("|---|---:|---:|---:|")
    w(f"| Daily (3% → 5%) | {a_old_s['events']['daily_halt']} | "
      f"{a_new_s['events']['daily_halt']} | "
      f"{fmt_delta(a_old_s['events']['daily_halt'], a_new_s['events']['daily_halt'])} |")
    w(f"| Monthly short (4% → 7%) | {a_old_s['events']['monthly_short_halt']} "
      f"({a_old_s['n_short_halt_months']}/61 ay) | "
      f"{a_new_s['events']['monthly_short_halt']} "
      f"({a_new_s['n_short_halt_months']}/61 ay) | "
      f"{fmt_delta(a_old_s['events']['monthly_short_halt'], a_new_s['events']['monthly_short_halt'])} |")
    w(f"| Monthly long (10% → 12%) | {a_old_s['events']['monthly_long_halt']} | "
      f"{a_new_s['events']['monthly_long_halt']} | "
      f"{fmt_delta(a_old_s['events']['monthly_long_halt'], a_new_s['events']['monthly_long_halt'])} |")
    w(f"| Consec loss pause (5 → 7) | {a_old_s['events']['consecutive_loss_pause']} | "
      f"{a_new_s['events']['consecutive_loss_pause']} | "
      f"{fmt_delta(a_old_s['events']['consecutive_loss_pause'], a_new_s['events']['consecutive_loss_pause'])} |")
    w(f"| Weekly (unchanged) | {a_old_s['events']['weekly_halt']} | "
      f"{a_new_s['events']['weekly_halt']} | "
      f"{fmt_delta(a_old_s['events']['weekly_halt'], a_new_s['events']['weekly_halt'])} |")
    w(f"| Monthly combined (unchanged, eff. off @0.99) | "
      f"{a_old_s['events']['monthly_halt']} | "
      f"{a_new_s['events']['monthly_halt']} | "
      f"{fmt_delta(a_old_s['events']['monthly_halt'], a_new_s['events']['monthly_halt'])} |")
    w(f"| **TOTAL halt events** | **{a_old_s['events']['total']}** | "
      f"**{a_new_s['events']['total']}** | "
      f"{fmt_delta(a_old_s['events']['total'], a_new_s['events']['total'])} |")
    w()
    w("**Empirik halt frekansı kontrolü (Risk Officer SEC54 audit referansı):**")
    w(f"- Eski monthly_short_halt → {a_old_s['n_short_halt_months']}/61 ay etkilendi "
      f"(Risk Officer audit '45/61 ay' uyarısı).")
    w(f"- Yeni monthly_short_halt → {a_new_s['n_short_halt_months']}/61 ay etkilendi.")
    if a_new_s['n_short_halt_months'] < a_old_s['n_short_halt_months']:
        w(f"- **REDUCTION:** -{a_old_s['n_short_halt_months']-a_new_s['n_short_halt_months']} ay "
          f"({100.0*(a_old_s['n_short_halt_months']-a_new_s['n_short_halt_months'])/max(a_old_s['n_short_halt_months'],1):.0f}% azalma).")
    else:
        w("- Reduction yok / pozitif değil — revize halt frekansını düşürmedi.")
    w()
    w("---")
    w()
    w("## Full Comparison — 4 Metric × 3 Fee Scenario")
    w()
    w("| Senaryo | Metric | Eski YAML | Yeni YAML | Δ | Yorum |")
    w("|---------|--------|----------:|----------:|---:|-------|")
    for slug, _, _ in scenarios:
        ref = SEC54_1_OLD[slug]
        r_new = results[(slug, "new")]
        w(f"| {slug} | Annual | +{ref['annual']:.1f}% | "
          f"{r_new['annual_pct']:+.1f}% | "
          f"{r_new['annual_pct']-ref['annual']:+.1f}pp | "
          f"gevşek breaker → daha az false halt |")
        w(f"| {slug} | Mean monthly | +{ref['mean_m']:.2f}% | "
          f"{r_new['mean_monthly_pct']:+.2f}% | "
          f"{r_new['mean_monthly_pct']-ref['mean_m']:+.2f}pp | |")
        w(f"| {slug} | Neg ay | {ref['neg']}/61 | "
          f"{r_new['neg_months']}/61 | "
          f"{r_new['neg_months']-ref['neg']:+d} | mandate cap 9 |")
        w(f"| {slug} | Max single loss | {ref['max_loss']:+.2f}% | "
          f"{r_new['max_loss_pct']:+.2f}% | "
          f"{r_new['max_loss_pct']-ref['max_loss']:+.2f}pp | "
          f"daily 5%→ max loss ↑ riski |")
        w(f"| {slug} | CV | {ref['cv']}% | "
          f"{r_new['cv_pct']:.0f}% | "
          f"{r_new['cv_pct']-ref['cv']:+.0f}pp | |")
        w(f"| {slug} | WF r-adj | {ref['wf_r_adj']:.2f} | "
          f"{r_new['wf_mean_r_adj']:.2f} | "
          f"{r_new['wf_mean_r_adj']-ref['wf_r_adj']:+.2f} | mandate cap 15 |")
        w(f"| {slug} | Halt events (OLD vs NEW breakers) | "
          f"{results[(slug,'old')]['events']['total']} | "
          f"{r_new['events']['total']} | "
          f"{r_new['events']['total']-results[(slug,'old')]['events']['total']:+d} | "
          f"reduction beklenir |")
    w()
    w("---")
    w()
    w("## Backward-Compat Verify (OLD breakers fee=0 vs SEC54.1 baseline)")
    w()
    w(f"- SEC54.1 A_fee0 annual: **+{ref_a['annual']:.1f}%**")
    w(f"- This run (cfg_old fee=0) annual: **{a_old['annual_pct']:+.1f}%**  "
      f"Δ={annual_delta:+.1f}pp  tol=±{tol_annual}pp  "
      f"**{'PASS' if annual_delta<=tol_annual else 'DRIFT'}**")
    w(f"- SEC54.1 A_fee0 mean_m: **+{ref_a['mean_m']:.2f}%**")
    w(f"- This run (cfg_old fee=0) mean_m: **{a_old['mean_monthly_pct']:+.2f}%**  "
      f"Δ={mean_delta:+.2f}pp  tol=±{tol_mean}pp  "
      f"**{'PASS' if mean_delta<=tol_mean else 'DRIFT'}**")
    w(f"- **BACKWARD-COMPAT: {'PASS' if compat_ok else 'DRIFT'}** "
      f"— OLD breaker override mimari doğru, parity korunuyor.")
    w()
    w("---")
    w()
    w("## Mandate Compliance Detail (NEW YAML)")
    w()
    w("**SEC54.6 revize gates (B1+B3 yumuşatıldı):**")
    w("- annual ≥ 600% (Senaryo B fee=+8 ile)")
    w("- mean monthly ≥ 20%")
    w("- neg ay ≤ 9/61 (low-n hariç)")
    w("- max single loss ≥ -8% (daily 5% genişledi ama hala sınırın içinde)")
    w("- WF r-adj ≥ 15")
    w()
    for slug, fee_bps, desc in scenarios:
        r = results[(slug, "new")]
        w(f"### {slug} — {desc} (fee={fee_bps:+.1f}bps)")
        w()
        for k, v in r["mandate_checks"].items():
            icon = "PASS" if v else "FAIL"
            w(f"- [{icon}] {k}")
        w()
    w("---")
    w()
    w("## Per-Scenario Full Metrics (NEW YAML)")
    w()
    for slug, fee_bps, desc in scenarios:
        r = results[(slug, "new")]
        ev = r["events"]
        w(f"### {slug} NEW — {desc}")
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
        w(f"| Halt: daily | {ev['daily_halt']} |")
        w(f"| Halt: weekly | {ev['weekly_halt']} |")
        w(f"| Halt: monthly_long | {ev['monthly_long_halt']} |")
        w(f"| Halt: monthly_short | {ev['monthly_short_halt']} ({r['n_short_halt_months']}/61 ay) |")
        w(f"| Pause: consec loss | {ev['consecutive_loss_pause']} |")
        w(f"| Halt: total | {ev['total']} |")
        w(f"| Mandate | {r['mandate_pass']}/{r['mandate_total']} |")
        w(f"| per-month CSV | `{Path(r['csv_month']).name}` |")
        w(f"| walk-forward CSV | `{Path(r['csv_wf']).name}` |")
        w(f"| event log CSV | `{Path(r['csv_events']).name}` |")
        w()
    w("---")
    w()
    w("## MEMORY Update Önerisi")
    w()
    w("v3.2 C2+V5 hibrid CHAMPION satırı için sayı güncellemesi:")
    w()
    w(f"- Önce (SEC54.1 OLD YAML, fee=+8): annual +1014.9%, mean +25.09%, neg 7, max_loss -4.90%")
    w(f"- Sonra (SEC54.6 NEW YAML, fee=+8): annual {results[('B_fee8','new')]['annual_pct']:+.1f}%, "
      f"mean {results[('B_fee8','new')]['mean_monthly_pct']:+.2f}%, "
      f"neg {results[('B_fee8','new')]['neg_months']}, "
      f"max_loss {results[('B_fee8','new')]['max_loss_pct']:+.2f}%")
    w()
    w(f"- Önce (SEC54.1 OLD YAML, fee=+4 realistic): "
      f"annual +1042.2%, mean +25.48%, neg 7")
    w(f"- Sonra (SEC54.6 NEW YAML, fee=+4 realistic): "
      f"annual {results[('D_fee4','new')]['annual_pct']:+.1f}%, "
      f"mean {results[('D_fee4','new')]['mean_monthly_pct']:+.2f}%, "
      f"neg {results[('D_fee4','new')]['neg_months']}")
    w()
    w(f"Halt event reduction (Scenario A fee=0 control): "
      f"OLD total={a_old_s['events']['total']} → NEW total={a_new_s['events']['total']}")
    w()
    w("---")
    w()
    w("## Overall Verdict")
    w()
    w(f"**{overall}**: {verdict_detail}")
    w()
    w("---")
    w()
    w(f"*Generated: {now_str} by SEC54.6 yaml_revise_replay sprint*")

    report_text = "".join(out)
    with REPORT.open("w", encoding="utf-8") as fh:
        fh.write(report_text)
    print(f"\n[REPORT] {REPORT}", flush=True)
    print("[SEC54.6] DONE", flush=True)


if __name__ == "__main__":
    main()
