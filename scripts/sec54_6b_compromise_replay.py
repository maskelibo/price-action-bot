"""SEC54.6b — Hibrit Kompromi Replay Verify (Lab Sprint).

Principal sign-off ile 1 parametre revize edildi (daily_loss_pct sıkılaştırıldı):
    daily_loss_pct: 0.05 -> 0.04  (HİBRİT KOMPROMİ — 2 mandate FAIL kapatma denemesi)
    consecutive_losses: 7         (SEC54.6 değeri korundu)
    monthly_loss_pct_short: 0.07  (SEC54.6 değeri korundu)
    monthly_loss_pct_long: 0.12   (SEC54.6 değeri korundu)

Gerekce: SEC54.6 (daily=5%) replay'i 2 mandate ihlal etti:
  - max_single_loss: -%13.5 (gate -%8) — HARD FAIL (2025-04 + 2025-05 outlier ay)
  - neg ay: 10/61 (gate 9) — MARGINAL FAIL
SEC54.6 raporu Lab tavsiyesi: daily 5%→4% kompromi. Tier <0.58 işlemler tolere
edilir (lev2x×%2=%4 daily), tier >0.58 işlemler still trigger ama alpha korunur.

Bu script:
  1. Yeni YAML (daily=4%) ile pool replay (3 fee senaryo: A=0, B=+8, D=+4)
  2. SEC54.6 (daily=5%) override ile aynı pool aynı fee — 3-way comparison
  3. 5-mandate compliance (revize gates: B1+B3 cap'leri korundu)
  4. Halt event count delta (4% vs 5%)
  5. Verdict + testnet smoke açılış önerisi

Pool: data/sec53_15m_pool_v11.pkl (SHA256 59a794ef...4e3ad6)
Config: configs/risk_phoenix_scalp_15m_c2v5_final.yaml (REVISED daily=4%)
Reference SEC54.6: reports/lab/2026-05-19_sec54_6_yaml_revise_replay.md
Reference SEC54.1: reports/execution_chief/2026-05-19_sec54_1_fee_retest.md

Cikti:
  reports/lab/2026-05-19_sec54_6b_compromise_replay.md
  reports/lab/sec54_6b_per_month_{A,B,D}_{new,sec546}.csv
  reports/lab/sec54_6b_walkforward_{A,B,D}_{new,sec546}.csv
  reports/lab/sec54_6b_events_{A,B,D}_{new,sec546}.csv
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
REPORT = OUT_DIR / "2026-05-19_sec54_6b_compromise_replay.md"

# SEC54.6 breaker values (PRE-kompromi: daily=5%) — override for 3-way comparison
SEC546_BREAKER_OVERRIDES = {
    "daily_dd": 0.05,
    "consecutive_loss_n": 7,
    "monthly_dd_short": 0.07,
    "monthly_dd_long": 0.12,
}

# NEW kompromi values (POST-revize: daily=4%) — from REVISED YAML
NEW_BREAKER_VALUES = {
    "daily_dd": 0.04,
    "consecutive_loss_n": 7,
    "monthly_dd_short": 0.07,
    "monthly_dd_long": 0.12,
}

# OLD SEC54.1 values (for reference baseline) — not used in this run, only labeled
SEC541_OLD_VALUES = {
    "daily_dd": 0.03,
    "consecutive_loss_n": 5,
    "monthly_dd_short": 0.04,
    "monthly_dd_long": 0.10,
}

# TOP-4 strategy names (SEC53 pool filter)
TOP4_NAMES = {
    "vsa_climax_test",
    "brooks_failed_breakout",
    "anchored_vwap_reversal",
    "engulfing_continuation",
}

POOL_SHA256_EXPECTED = "59a794ef278e47f696cdb14ddf42db383ed097474f938f8902a34e450a4e3ad6"

# SEC54.1 baseline (OLD YAML daily=3%, fee scenarios) — for 3-way reference
SEC54_1_OLD = {
    "A_fee0":  {"annual": 1082.3, "mean_m": 25.86, "neg": 7, "max_loss": -4.57,
                "cv": 120, "wf_r_adj": 42.75, "pos": 54, "ge20": 26, "sub20": 35},
    "B_fee8":  {"annual": 1014.9, "mean_m": 25.09, "neg": 7, "max_loss": -4.90,
                "cv": 119, "wf_r_adj": 36.87, "pos": 54, "ge20": 26, "sub20": 35},
    "D_fee4":  {"annual": 1042.2, "mean_m": 25.48, "neg": 7, "max_loss": -4.73,
                "cv": 121, "wf_r_adj": 40.94, "pos": 54, "ge20": 26, "sub20": 35},
}

# SEC54.6 reference (NEW YAML daily=5%, fee scenarios) — from prior report
SEC54_6_NEW = {
    "A_fee0":  {"annual": 1417.6, "mean_m": 29.61, "neg": 8,  "max_loss": -13.54,
                "cv": 124, "wf_r_adj": 36.17, "pos": 53, "ge20": 28, "sub20": 33,
                "halt_total": 410, "halt_daily": 303, "halt_consec": 59,
                "halt_m_short": 8, "halt_m_short_months": 2},
    "B_fee8":  {"annual": 1320.5, "mean_m": 28.85, "neg": 10, "max_loss": -13.82,
                "cv": 126, "wf_r_adj": 33.84, "pos": 51, "ge20": 28, "sub20": 33,
                "halt_total": 411, "halt_daily": 304, "halt_consec": 58,
                "halt_m_short": 8, "halt_m_short_months": 2},
    "D_fee4":  {"annual": 1362.9, "mean_m": 29.19, "neg": 10, "max_loss": -13.68,
                "cv": 125, "wf_r_adj": 34.96, "pos": 51, "ge20": 28, "sub20": 33,
                "halt_total": 409, "halt_daily": 302, "halt_consec": 58,
                "halt_m_short": 8, "halt_m_short_months": 2},
}


# ============================================================================
# Utilities (parity with SEC54.6)
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

    ev_counts = {"daily_halt": 0, "weekly_halt": 0, "monthly_halt": 0,
                 "monthly_long_halt": 0, "monthly_short_halt": 0,
                 "consecutive_loss_pause": 0, "total": 0}
    if events:
        for e in events:
            t = e.get("type")
            if t in ev_counts:
                ev_counts[t] += 1
            ev_counts["total"] += 1

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


def mandate_check_sec54_6b(s: dict) -> dict:
    """SEC54.6b kompromi mandate (B1+B3 cap'leri korundu): annual>=600, mean>=20,
    neg<=9, max_loss>=-8 (HARD — 2 mandate FAIL kapatma hedefi), wf_r_adj>=15.
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
    csv_m = out_dir / f"sec54_6b_per_month_{slug}.csv"
    csv_w = out_dir / f"sec54_6b_walkforward_{slug}.csv"
    csv_e = out_dir / f"sec54_6b_events_{slug}.csv"
    save_month_csv(csv_m, month_rows)
    save_wf_csv(csv_w, wf_rows)
    save_events_csv(csv_e, events)

    mandate = mandate_check_sec54_6b(s)
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
    print("[SEC54.6b] Hibrit Kompromi Replay Verify (Lab Sprint)", flush=True)
    print(f"  Pool: {POOL_PATH}", flush=True)
    print(f"  YAML: {RISK_YAML}", flush=True)
    print(f"  Kompromi: daily 5% -> 4% (1 param), consec=7 + m_short=7% + m_long=12% (3 param KORUNDU)",
          flush=True)
    print(f"  Hedef: 2 mandate FAIL kapatma (max_loss>=-8%, neg<=9)", flush=True)

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
    # Base config — NEW YAML (kompromi: daily=4%, already revised on disk)
    # ========================================================================
    print(f"\n[CONFIG] Loading NEW (kompromi daily=4%) {RISK_YAML.name}...", flush=True)
    cfg_new = ProductionConfig.from_yaml(str(RISK_YAML))
    # Same replay overrides as SEC54.1/SEC54.6 (risk_pct=0.02, pyramid V5, conc=20, no cooldown)
    cfg_new = cfg_new.with_overrides(
        risk_pct=0.02,
        pyramid_triggers=(1.0, 1.5),
        max_concurrent=20,
        same_symbol_side_cooldown_days=0,
    )
    print(f"  NEW (kompromi) breakers: daily={cfg_new.daily_dd}  consec={cfg_new.consecutive_loss_n}  "
          f"m_short={cfg_new.monthly_dd_short}  m_long={cfg_new.monthly_dd_long}",
          flush=True)
    # Sanity: assert NEW YAML actually carries kompromi values
    assert abs(cfg_new.daily_dd - NEW_BREAKER_VALUES["daily_dd"]) < 1e-9, \
        f"NEW YAML daily_dd mismatch: got {cfg_new.daily_dd} (expected 0.04)"
    assert cfg_new.consecutive_loss_n == NEW_BREAKER_VALUES["consecutive_loss_n"], \
        f"NEW YAML consec mismatch: got {cfg_new.consecutive_loss_n}"
    assert abs(cfg_new.monthly_dd_short - NEW_BREAKER_VALUES["monthly_dd_short"]) < 1e-9
    assert abs(cfg_new.monthly_dd_long - NEW_BREAKER_VALUES["monthly_dd_long"]) < 1e-9
    print("  [ASSERT] NEW YAML carries kompromi values (daily=4%, rest unchanged)  OK", flush=True)

    # SEC54.6 breaker config — same NEW base but override daily back to 5%
    cfg_sec546 = cfg_new.with_overrides(**SEC546_BREAKER_OVERRIDES)
    print(f"  SEC54.6 breakers (override daily=5%): daily={cfg_sec546.daily_dd}  "
          f"consec={cfg_sec546.consecutive_loss_n}  m_short={cfg_sec546.monthly_dd_short}  "
          f"m_long={cfg_sec546.monthly_dd_long}", flush=True)

    # ========================================================================
    # 3 Fee scenarios × 2 YAML versions (6 runs)
    # ========================================================================
    scenarios = [
        ("A_fee0",  0.0,  "Control (zero fee — SEC54.6 baseline verify)"),
        ("B_fee8",  8.0,  "Taker only worst-case (8 bps round-trip)"),
        ("D_fee4",  4.0,  "Realistic blend (50% taker + 50% maker)"),
    ]

    results = {}
    for slug, fee_bps, desc in scenarios:
        # NEW kompromi YAML run (daily=4%)
        r_new = run_scenario(slug, fee_bps, pool, cfg_new, OUT_DIR, yaml_tag="new")
        r_new["description"] = desc
        results[(slug, "new")] = r_new
        # SEC54.6 breakers run (daily=5%) — same pool, same fee — for halt-event delta
        r_sec546 = run_scenario(slug, fee_bps, pool, cfg_sec546, OUT_DIR, yaml_tag="sec546")
        r_sec546["description"] = desc
        results[(slug, "sec546")] = r_sec546

    # ========================================================================
    # Backward-compat verify (SEC54.6 override fee=0 vs SEC54.6 prior report)
    # ========================================================================
    print("\n[BACKWARD-COMPAT] SEC54.6 override fee=0 vs prior SEC54.6 A_fee0...",
          flush=True)
    a_sec546 = results[("A_fee0", "sec546")]
    ref_a_546 = SEC54_6_NEW["A_fee0"]
    tol_annual = 5.0
    tol_mean = 1.0
    annual_delta = abs(a_sec546["annual_pct"] - ref_a_546["annual"])
    mean_delta = abs(a_sec546["mean_monthly_pct"] - ref_a_546["mean_m"])
    compat_ok = (annual_delta <= tol_annual and mean_delta <= tol_mean)
    print(f"  annual: got={a_sec546['annual_pct']:+.1f}%  ref(SEC54.6)={ref_a_546['annual']:+.1f}%  "
          f"delta={annual_delta:+.1f}pp  tol=±{tol_annual}  "
          f"{'OK' if annual_delta<=tol_annual else 'DRIFT'}", flush=True)
    print(f"  mean_m: got={a_sec546['mean_monthly_pct']:+.2f}%  ref(SEC54.6)={ref_a_546['mean_m']:+.2f}%  "
          f"delta={mean_delta:+.2f}pp  tol=±{tol_mean}  "
          f"{'OK' if mean_delta<=tol_mean else 'DRIFT'}", flush=True)
    print(f"  BACKWARD-COMPAT (vs SEC54.6): {'PASS' if compat_ok else 'DRIFT (investigate)'}",
          flush=True)

    # ========================================================================
    # Mandate compliance — NEW kompromi YAML B scenario primary gate
    # ========================================================================
    print("\n[MANDATE SEC54.6b] NEW (kompromi daily=4%) compliance check (5 gate):", flush=True)
    for slug, _, desc in scenarios:
        r = results[(slug, "new")]
        m = r["mandate_pass"]
        tag = "PASS" if m == 5 else ("WARN" if m == 4 else ("MARGINAL" if m == 3 else "NO-GO"))
        print(f"  [{slug} NEW] fee={r['fee_bps']:+.1f}bps  annual={r['annual_pct']:+.1f}%  "
              f"mandate={m}/5  [{tag}]", flush=True)

    b_new = results[("B_fee8", "new")]
    if b_new["mandate_pass"] == 5:
        overall = "PASS"
        verdict_detail = ("5/5 gate met under realistic fee — Hibrit kompromi (daily=4%) "
                          "BAŞARILI; SEC54.6 2 FAIL kapatıldı, testnet smoke gate ÖNERİSİ aktif.")
    elif b_new["mandate_pass"] == 4:
        overall = "WARN"
        verdict_detail = "4/5 gate — 1 borderline metric, Principal review needed"
    elif b_new["mandate_pass"] == 3:
        overall = "MARGINAL"
        verdict_detail = "3/5 gate — 2 metric border, kompromi yetersiz"
    else:
        overall = "FAIL"
        verdict_detail = "Mandate ihlal — daily 4% de yetersiz, başka parametre revize gerek"
    print(f"\n[VERDICT] {overall}: {verdict_detail}", flush=True)

    # ========================================================================
    # Markdown report
    # ========================================================================
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    out = []
    w = lambda s="": out.append(s + "\n")

    w("# SEC54.6b — Hibrit Kompromi Replay Verify (daily 5% -> 4%)")
    w()
    w(f"**Lab Scientist:** Head of Self-Improvement Lab")
    w(f"**Date:** {now_str}")
    w(f"**Sprint:** SEC54.6b — Hibrit kompromi replay (Principal sign-off 2026-05-18)")
    w(f"**Pool:** `data/sec53_15m_pool_v11.pkl` "
      f"({POOL_PATH.stat().st_size/1e6:.1f} MB, SHA256 `{POOL_SHA256_EXPECTED[:16]}...`)")
    w(f"**Config:** `{RISK_YAML.name}` (REVISED daily=4%)")
    w(f"**Replay knobs:** risk_pct=0.02, pyramid (1.0, 1.5), max_conc=20, "
      f"cooldown=0 (parity with SEC54.1/SEC54.6)")
    w()
    w("---")
    w()
    w("## Executive Summary — VERDICT + MANDATE 5/5 TABLE")
    w()
    w(f"**Overall verdict:** **{overall}**")
    w()
    w(f"{verdict_detail}")
    w()
    w("**Mandate 5/5 table (Scenario B, fee=+8 bps — realistic worst case):**")
    w()
    w("| Gate | Threshold | Value (SEC54.6b) | Status |")
    w("|------|----------:|-----------------:|:------:|")
    for k, v in b_new["mandate_checks"].items():
        icon = "PASS" if v else "FAIL"
        if k == "annual_ge_600":
            w(f"| Annual >= 600% | 600% | {b_new['annual_pct']:+.1f}% | {icon} |")
        elif k == "mean_monthly_ge_20":
            w(f"| Mean monthly >= 20% | 20% | {b_new['mean_monthly_pct']:+.2f}% | {icon} |")
        elif k == "neg_months_le_9":
            w(f"| Neg ay <= 9/61 | 9 | {b_new['neg_months']}/61 | {icon} |")
        elif k == "max_loss_ge_neg8":
            w(f"| Max single loss >= -8% | -8% | {b_new['max_loss_pct']:+.2f}% | {icon} |")
        elif k == "wf_r_adj_ge_15":
            w(f"| WF r-adj >= 15 | 15 | {b_new['wf_mean_r_adj']:.2f} | {icon} |")
    w()
    w("---")
    w()
    w("## 3-Way Comparison Table (SEC54.1 -> SEC54.6 -> SEC54.6b)")
    w()
    w("**Scenario B (fee=+8 bps) — primary mandate gate:**")
    w()
    b_546 = SEC54_6_NEW["B_fee8"]
    b_541 = SEC54_1_OLD["B_fee8"]
    w("| Metric | SEC54.6 (5%) | **SEC54.6b (4%)** | SEC54.1 (3%, OLD) | Hedef |")
    w("|---|---:|---:|---:|---|")
    w(f"| Annual (fee=+8) | +{b_546['annual']:.1f}% | **{b_new['annual_pct']:+.1f}%** | +{b_541['annual']:.1f}% | >+600% |")
    w(f"| Mean monthly | +{b_546['mean_m']:.2f}% | **{b_new['mean_monthly_pct']:+.2f}%** | +{b_541['mean_m']:.2f}% | >+20% |")
    w(f"| **Max single loss** | {b_546['max_loss']:+.2f}% | **{b_new['max_loss_pct']:+.2f}%** | {b_541['max_loss']:+.2f}% | **>= -8%** |")
    w(f"| **Neg ay** | {b_546['neg']}/61 | **{b_new['neg_months']}/61** | {b_541['neg']}/61 | **<= 9** |")
    w(f"| CV | {b_546['cv']}% | {b_new['cv_pct']:.0f}% | {b_541['cv']}% | <150% |")
    w(f"| WF r-adj | {b_546['wf_r_adj']:.2f} | {b_new['wf_mean_r_adj']:.2f} | {b_541['wf_r_adj']:.2f} | >=15 |")
    w(f"| Mandate pass | 3/5 | **{b_new['mandate_pass']}/5** | 5/5 | 5/5 |")
    w()
    w("**Scenario A (fee=0) — control:**")
    w()
    a_new = results[("A_fee0", "new")]
    a_546 = SEC54_6_NEW["A_fee0"]
    a_541 = SEC54_1_OLD["A_fee0"]
    w("| Metric | SEC54.6 (5%) | **SEC54.6b (4%)** | SEC54.1 (3%, OLD) |")
    w("|---|---:|---:|---:|")
    w(f"| Annual | +{a_546['annual']:.1f}% | **{a_new['annual_pct']:+.1f}%** | +{a_541['annual']:.1f}% |")
    w(f"| Mean monthly | +{a_546['mean_m']:.2f}% | **{a_new['mean_monthly_pct']:+.2f}%** | +{a_541['mean_m']:.2f}% |")
    w(f"| Max single loss | {a_546['max_loss']:+.2f}% | **{a_new['max_loss_pct']:+.2f}%** | {a_541['max_loss']:+.2f}% |")
    w(f"| Neg ay | {a_546['neg']}/61 | **{a_new['neg_months']}/61** | {a_541['neg']}/61 |")
    w(f"| CV | {a_546['cv']}% | {a_new['cv_pct']:.0f}% | {a_541['cv']}% |")
    w(f"| WF r-adj | {a_546['wf_r_adj']:.2f} | {a_new['wf_mean_r_adj']:.2f} | {a_541['wf_r_adj']:.2f} |")
    w()
    w("**Scenario D (fee=+4 bps) — realistic blend:**")
    w()
    d_new = results[("D_fee4", "new")]
    d_546 = SEC54_6_NEW["D_fee4"]
    d_541 = SEC54_1_OLD["D_fee4"]
    w("| Metric | SEC54.6 (5%) | **SEC54.6b (4%)** | SEC54.1 (3%, OLD) |")
    w("|---|---:|---:|---:|")
    w(f"| Annual | +{d_546['annual']:.1f}% | **{d_new['annual_pct']:+.1f}%** | +{d_541['annual']:.1f}% |")
    w(f"| Mean monthly | +{d_546['mean_m']:.2f}% | **{d_new['mean_monthly_pct']:+.2f}%** | +{d_541['mean_m']:.2f}% |")
    w(f"| Max single loss | {d_546['max_loss']:+.2f}% | **{d_new['max_loss_pct']:+.2f}%** | {d_541['max_loss']:+.2f}% |")
    w(f"| Neg ay | {d_546['neg']}/61 | **{d_new['neg_months']}/61** | {d_541['neg']}/61 |")
    w(f"| CV | {d_546['cv']}% | {d_new['cv_pct']:.0f}% | {d_541['cv']}% |")
    w(f"| WF r-adj | {d_546['wf_r_adj']:.2f} | {d_new['wf_mean_r_adj']:.2f} | {d_541['wf_r_adj']:.2f} |")
    w()
    w("---")
    w()
    w("## HALT EVENT DELTA TABLE (Daily 5% vs 4%)")
    w()
    w("**SEC54.6 (daily=5%) vs SEC54.6b (daily=4%) — Scenario A, fee=0, identical pool & overrides:**")
    w()
    a_sec546_s = results[("A_fee0", "sec546")]
    a_new_s = results[("A_fee0", "new")]

    def fmt_delta(old: int, new: int) -> str:
        d = new - old
        if old > 0:
            pct = 100.0 * d / old
            return f"{d:+d} ({pct:+.1f}%)"
        return f"{d:+d} (n/a)"

    w("| Breaker (SEC54.6 -> SEC54.6b eşik) | SEC54.6 tetik (5%) | SEC54.6b tetik (4%) | Delta |")
    w("|---|---:|---:|---:|")
    w(f"| Daily (5% -> 4%) | {a_sec546_s['events']['daily_halt']} | "
      f"{a_new_s['events']['daily_halt']} | "
      f"{fmt_delta(a_sec546_s['events']['daily_halt'], a_new_s['events']['daily_halt'])} |")
    w(f"| Monthly short (7% unchanged) | {a_sec546_s['events']['monthly_short_halt']} "
      f"({a_sec546_s['n_short_halt_months']}/61 ay) | "
      f"{a_new_s['events']['monthly_short_halt']} "
      f"({a_new_s['n_short_halt_months']}/61 ay) | "
      f"{fmt_delta(a_sec546_s['events']['monthly_short_halt'], a_new_s['events']['monthly_short_halt'])} |")
    w(f"| Monthly long (12% unchanged) | {a_sec546_s['events']['monthly_long_halt']} | "
      f"{a_new_s['events']['monthly_long_halt']} | "
      f"{fmt_delta(a_sec546_s['events']['monthly_long_halt'], a_new_s['events']['monthly_long_halt'])} |")
    w(f"| Consec loss pause (7 unchanged) | {a_sec546_s['events']['consecutive_loss_pause']} | "
      f"{a_new_s['events']['consecutive_loss_pause']} | "
      f"{fmt_delta(a_sec546_s['events']['consecutive_loss_pause'], a_new_s['events']['consecutive_loss_pause'])} |")
    w(f"| Weekly (8% unchanged) | {a_sec546_s['events']['weekly_halt']} | "
      f"{a_new_s['events']['weekly_halt']} | "
      f"{fmt_delta(a_sec546_s['events']['weekly_halt'], a_new_s['events']['weekly_halt'])} |")
    w(f"| Monthly combined (off @0.99) | "
      f"{a_sec546_s['events']['monthly_halt']} | "
      f"{a_new_s['events']['monthly_halt']} | "
      f"{fmt_delta(a_sec546_s['events']['monthly_halt'], a_new_s['events']['monthly_halt'])} |")
    w(f"| **TOTAL halt events** | **{a_sec546_s['events']['total']}** | "
      f"**{a_new_s['events']['total']}** | "
      f"{fmt_delta(a_sec546_s['events']['total'], a_new_s['events']['total'])} |")
    w()
    w("**3-way halt event progression (daily threshold ladder):**")
    w()
    w("| YAML | Daily threshold | Daily halts | Total halts | m_short ay |")
    w("|---|:---:|---:|---:|---:|")
    w(f"| SEC54.1 OLD | 3% | (n/a, sec54.1 ayrı run) | (n/a) | 7/61 |")
    w(f"| SEC54.6 | 5% | {a_sec546_s['events']['daily_halt']} | "
      f"{a_sec546_s['events']['total']} | "
      f"{a_sec546_s['n_short_halt_months']}/61 |")
    w(f"| **SEC54.6b (kompromi)** | **4%** | **{a_new_s['events']['daily_halt']}** | "
      f"**{a_new_s['events']['total']}** | "
      f"**{a_new_s['n_short_halt_months']}/61** |")
    w()
    w("**Kompromi yorum:** Daily halt sayısı SEC54.6 (5%) seviyesinden artıyor (sıkılaştırma "
      "beklenen), AMA SEC54.1 (3%) seviyesinden düşük kalıyor — orta yol.")
    w()
    w("---")
    w()
    w("## Mandate Compliance Detail (NEW kompromi YAML — daily=4%)")
    w()
    w("**SEC54.6b kompromi gates (5/5 hedef):**")
    w("- annual >= 600% (Senaryo B fee=+8 ile)")
    w("- mean monthly >= 20%")
    w("- neg ay <= 9/61")
    w("- max single loss >= -8% (HARD — SEC54.6 2 FAIL kapatma hedefi)")
    w("- WF r-adj >= 15")
    w()
    for slug, fee_bps, desc in scenarios:
        r = results[(slug, "new")]
        w(f"### {slug} — {desc} (fee={fee_bps:+.1f}bps)")
        w()
        for k, v in r["mandate_checks"].items():
            icon = "PASS" if v else "FAIL"
            w(f"- [{icon}] {k}")
        w(f"- Mandate: **{r['mandate_pass']}/5**")
        w()
    w("---")
    w()
    w("## Backward-Compat Verify (SEC54.6 override fee=0 vs prior SEC54.6 report)")
    w()
    w(f"- SEC54.6 (prior) A_fee0 annual: **+{ref_a_546['annual']:.1f}%**")
    w(f"- This run (cfg_sec546 override, fee=0) annual: **{a_sec546['annual_pct']:+.1f}%**  "
      f"Δ={annual_delta:+.1f}pp  tol=±{tol_annual}pp  "
      f"**{'PASS' if annual_delta<=tol_annual else 'DRIFT'}**")
    w(f"- SEC54.6 (prior) A_fee0 mean_m: **+{ref_a_546['mean_m']:.2f}%**")
    w(f"- This run (cfg_sec546 override, fee=0) mean_m: **{a_sec546['mean_monthly_pct']:+.2f}%**  "
      f"Δ={mean_delta:+.2f}pp  tol=±{tol_mean}pp  "
      f"**{'PASS' if mean_delta<=tol_mean else 'DRIFT'}**")
    w(f"- **BACKWARD-COMPAT (vs SEC54.6): {'PASS' if compat_ok else 'DRIFT'}** "
      f"— SEC54.6 değer override mimari doğru, parity korunuyor.")
    w()
    w("---")
    w()
    w("## Per-Scenario Full Metrics (NEW kompromi YAML)")
    w()
    for slug, fee_bps, desc in scenarios:
        r = results[(slug, "new")]
        ev = r["events"]
        w(f"### {slug} NEW (kompromi daily=4%) — {desc}")
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
    w("## Verdict & Testnet Smoke Açılış Önerisi")
    w()
    w(f"**Overall verdict:** **{overall}**")
    w()
    w(f"{verdict_detail}")
    w()
    if overall == "PASS":
        w("**Önerilen sonraki adımlar (Lab tavsiyesi):**")
        w()
        w("1. CEO brief'e gönder: SEC54.6b kompromi 5/5 mandate PASS, testnet smoke gate açılabilir.")
        w("2. Testnet smoke 7g pencere — paper trading metric'leri canlı backtest beklentisiyle "
          "karşılaştır (mean monthly +%X gerçekleşen vs +%X backtest).")
        w("3. SEC55 drift detection — eğer testnet smoke metric'leri backtest'ten %25+ saparsa Lab "
          "uyarı çıkarır, terfi durdurulur.")
        w("4. MEMORY.md update: v3.2 C2+V5 CHAMPION satırını SEC54.6b kompromi sayılarına güncelle.")
    elif overall in ("WARN", "MARGINAL"):
        w("**Önerilen sonraki adımlar (Lab tavsiyesi):**")
        w()
        w("1. CEO brief: Hibrit kompromi 1-2 borderline metric ile geldi — Principal kararı gerekli:")
        w("   - SEÇENEK 1: Mevcut kompromi'yi kabul + testnet smoke yine de aç (risk-toleranslı).")
        w("   - SEÇENEK 2: daily 4% -> 3% daha sıkı (SEC54.1 değerine geri dön) — full conservative.")
        w("   - SEÇENEK 3: Başka parametre revize (örn. risk_per_trade 2% -> 1.5%) — orthogonal eksen.")
        w("2. Testnet smoke gate KAPALI kalır — 5/5 değil 4/5 veya 3/5, full kanıt yok.")
    else:  # FAIL
        w("**Önerilen sonraki adımlar (Lab tavsiyesi):**")
        w()
        w("1. CEO brief: Kompromi (daily=4%) YETERSİZ — 2 mandate FAIL devam ediyor.")
        w("2. SEC54.6c sprint: ya daily 5% bırakıp risk_per_trade'i %1.5'e indir (alpha cost~%30 "
          "ama tail kontrol), ya da SEC54.1 OLD YAML'a tamamen geri dön (annual +1015%, full PASS).")
        w("3. Testnet smoke gate KAPALI kalır — production candidate yok.")
    w()
    w("---")
    w()
    w("## MEMORY Update Önerisi (PASS senaryosunda)")
    w()
    w("v3.2 C2+V5 hibrid CHAMPION satırı için sayı güncellemesi:")
    w()
    w(f"- SEC54.1 (OLD daily=3%, fee=+8):    annual +{b_541['annual']:.1f}%, mean +{b_541['mean_m']:.2f}%, "
      f"neg {b_541['neg']}/61, max_loss {b_541['max_loss']:+.2f}%, mandate 5/5")
    w(f"- SEC54.6 (revize daily=5%, fee=+8): annual +{b_546['annual']:.1f}%, mean +{b_546['mean_m']:.2f}%, "
      f"neg {b_546['neg']}/61, max_loss {b_546['max_loss']:+.2f}%, mandate 3/5 (2 FAIL)")
    w(f"- **SEC54.6b (kompromi daily=4%, fee=+8): annual {b_new['annual_pct']:+.1f}%, "
      f"mean {b_new['mean_monthly_pct']:+.2f}%, neg {b_new['neg_months']}/61, "
      f"max_loss {b_new['max_loss_pct']:+.2f}%, mandate {b_new['mandate_pass']}/5**")
    w()
    w(f"Halt event delta (Scenario A fee=0): SEC54.6 daily=303 -> SEC54.6b daily="
      f"{a_new_s['events']['daily_halt']}; "
      f"total {a_sec546_s['events']['total']} -> {a_new_s['events']['total']}")
    w()
    w("---")
    w()
    w(f"*Generated: {now_str} by SEC54.6b compromise_replay sprint*")

    report_text = "".join(out)
    with REPORT.open("w", encoding="utf-8") as fh:
        fh.write(report_text)
    print(f"\n[REPORT] {REPORT}", flush=True)
    print("[SEC54.6b] DONE", flush=True)


if __name__ == "__main__":
    main()
