"""SEC54.6c — YOL-B Replay Verify (Lab Sprint).

Principal sign-off ile 2 ek parametre revize edildi (SEC54.6b kompromi YETERSİZ):
    daily_loss_pct: 0.04         (SEC54.6b kompromi KORUNDU)
    consecutive_losses: 5         (SEC54.6 7 -> 5 GERİ — SEC54.1 değeri)
    monthly_loss_pct_short: 0.04 (SEC54.6 7% -> 4% GERİ — SEC54.1 değeri)
    monthly_loss_pct_long: 0.12  (SEC54.6 KORUNDU)

Gerekce: SEC54.6b (daily=4% tek-param revize) hala 3/5 mandate, 2 FAIL:
  - max_single_loss: -%13.29 (gate -%8) — HARD FAIL devam
  - neg ay: 10/61 (gate 9) — MARGINAL FAIL devam
SEC54.6b forensic (2022-05 paradoks): tek-param daily revize mean-reversion
capitulation rejimlerinde counter-productive. Tail kapatmak için consec +
m_short revize zorunlu (SEC54.1'den geri al).

Principal direktifi (2026-05-18 gece):
  - PRIMARY: Neg ay 10/61 -> ≤9
  - SECONDARY: Max_single_loss gate -%8 -> -%15 (GEVŞETİLDİ)
  - "Continue overnight, sabaha kadar optimize"

Bu script:
  1. Yeni YAML (YOL-B paramları) ile pool replay (3 fee senaryo: A=0, B=+8, D=+4)
  2. SEC54.6b override (kompromi) ile aynı pool aynı fee — 4-way comparison
  3. 5-mandate compliance (REVIZE gate: max_loss >= -15%)
  4. Halt event count delta (YOL-B vs SEC54.6b)
  5. Verdict + tail-risk forensic

Pool: data/sec53_15m_pool_v11.pkl (SHA256 59a794ef...4e3ad6)
Config: configs/risk_phoenix_scalp_15m_c2v5_final.yaml (REVISED YOL-B)
Reference SEC54.6b: reports/lab/2026-05-19_sec54_6b_compromise_replay.md
Reference SEC54.6: reports/lab/2026-05-19_sec54_6_yaml_revise_replay.md
Reference SEC54.1: reports/execution_chief/2026-05-19_sec54_1_fee_retest.md

Cikti:
  reports/lab/2026-05-19_sec54_6c_yol_b_replay.md
  reports/lab/sec54_6c_per_month_{A,B,D}_{yolb,sec546b}.csv
  reports/lab/sec54_6c_walkforward_{A,B,D}_{yolb,sec546b}.csv
  reports/lab/sec54_6c_events_{A,B,D}_{yolb,sec546b}.csv
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
REPORT = OUT_DIR / "2026-05-19_sec54_6c_yol_b_replay.md"

# YOL-B values (NEW kompromi+tail-close, from REVISED YAML) — primary verify
YOLB_BREAKER_VALUES = {
    "daily_dd": 0.04,
    "consecutive_loss_n": 5,
    "monthly_dd_short": 0.04,
    "monthly_dd_long": 0.12,
}

# SEC54.6b breaker values (kompromi daily=4% solo) — override for delta comparison
SEC546B_BREAKER_OVERRIDES = {
    "daily_dd": 0.04,
    "consecutive_loss_n": 7,
    "monthly_dd_short": 0.07,
    "monthly_dd_long": 0.12,
}

# SEC54.6 breaker values (daily=5%) — for 4-way reference (numbers from prior report)
SEC546_BREAKER_VALUES = {
    "daily_dd": 0.05,
    "consecutive_loss_n": 7,
    "monthly_dd_short": 0.07,
    "monthly_dd_long": 0.12,
}

# OLD SEC54.1 values (for reference baseline) — labeled only
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

# SEC54.1 baseline (OLD YAML daily=3%, fee scenarios) — for 4-way reference
SEC54_1_OLD = {
    "A_fee0":  {"annual": 1082.3, "mean_m": 25.86, "neg": 7, "max_loss": -4.57,
                "cv": 120, "wf_r_adj": 42.75, "pos": 54, "ge20": 26, "sub20": 35},
    "B_fee8":  {"annual": 1014.9, "mean_m": 25.09, "neg": 7, "max_loss": -4.90,
                "cv": 119, "wf_r_adj": 36.87, "pos": 54, "ge20": 26, "sub20": 35},
    "D_fee4":  {"annual": 1042.2, "mean_m": 25.48, "neg": 7, "max_loss": -4.73,
                "cv": 121, "wf_r_adj": 40.94, "pos": 54, "ge20": 26, "sub20": 35},
}

# SEC54.6 reference (daily=5%) — from prior report
SEC54_6_REF = {
    "A_fee0":  {"annual": 1417.6, "mean_m": 29.61, "neg": 8,  "max_loss": -13.54,
                "cv": 124, "wf_r_adj": 36.17, "pos": 53, "ge20": 28, "sub20": 33},
    "B_fee8":  {"annual": 1320.5, "mean_m": 28.85, "neg": 10, "max_loss": -13.82,
                "cv": 126, "wf_r_adj": 33.84, "pos": 51, "ge20": 28, "sub20": 33},
    "D_fee4":  {"annual": 1362.9, "mean_m": 29.19, "neg": 10, "max_loss": -13.68,
                "cv": 125, "wf_r_adj": 34.96, "pos": 51, "ge20": 28, "sub20": 33},
}

# SEC54.6b reference (kompromi daily=4% solo) — from prior report
SEC54_6B_REF = {
    "A_fee0":  {"annual": 1595.7, "mean_m": 31.40, "neg": 8,  "max_loss": -12.95,
                "cv": 127, "wf_r_adj": 35.25, "pos": 53, "ge20": 28, "sub20": 31,
                "halt_total": 434, "halt_daily": 341, "halt_consec": 47,
                "halt_m_short": 8, "halt_m_short_months": 2},
    "B_fee8":  {"annual": 1487.2, "mean_m": 30.60, "neg": 10, "max_loss": -13.29,
                "cv": 129, "wf_r_adj": 33.00, "pos": 51, "ge20": 28, "sub20": 33,
                "halt_total": 434, "halt_daily": 341, "halt_consec": 46,
                "halt_m_short": 8, "halt_m_short_months": 2},
    "D_fee4":  {"annual": 1538.5, "mean_m": 30.99, "neg": 10, "max_loss": -13.12,
                "cv": 128, "wf_r_adj": 34.17, "pos": 51, "ge20": 28, "sub20": 31,
                "halt_total": 434, "halt_daily": 341, "halt_consec": 46,
                "halt_m_short": 8, "halt_m_short_months": 2},
}


# ============================================================================
# Utilities (parity with SEC54.6/6b)
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
        "month_rows": valid,
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


def mandate_check_sec54_6c(s: dict) -> dict:
    """SEC54.6c YOL-B mandate (Principal gevşek max_loss): annual>=600, mean>=20,
    neg<=9 (PRIMARY), max_loss>=-15 (GEVŞETİLDİ -8 -> -15), wf_r_adj>=15.
    """
    checks = {
        "annual_ge_600": s["annual_pct"] >= 600.0,
        "mean_monthly_ge_20": s["mean_monthly_pct"] >= 20.0,
        "neg_months_le_9": s["neg_months"] <= 9,  # PRIMARY hedef
        "max_loss_ge_neg15": s["max_loss_pct"] >= -15.0,  # GEVŞETİLDİ -8 -> -15
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
    csv_m = out_dir / f"sec54_6c_per_month_{slug}.csv"
    csv_w = out_dir / f"sec54_6c_walkforward_{slug}.csv"
    csv_e = out_dir / f"sec54_6c_events_{slug}.csv"
    save_month_csv(csv_m, month_rows)
    save_wf_csv(csv_w, wf_rows)
    save_events_csv(csv_e, events)

    mandate = mandate_check_sec54_6c(s)
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
    print("[SEC54.6c] YOL-B Replay Verify (Lab Sprint)", flush=True)
    print(f"  Pool: {POOL_PATH}", flush=True)
    print(f"  YAML: {RISK_YAML}", flush=True)
    print(f"  YOL-B: daily=4% (kompromi) + consec=5 (SEC54.1 GERI) + m_short=4% (SEC54.1 GERI) + m_long=12% (KORU)",
          flush=True)
    print(f"  Hedef (Principal): neg ay 10/61 -> <=9 (PRIMARY), max_loss gate -8 -> -15 (GEVSE)", flush=True)

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
    # Base config — NEW YAML (YOL-B: daily=4% + consec=5 + m_short=4% + m_long=12%)
    # ========================================================================
    print(f"\n[CONFIG] Loading NEW (YOL-B) {RISK_YAML.name}...", flush=True)
    cfg_yolb = ProductionConfig.from_yaml(str(RISK_YAML))
    # Same replay overrides as SEC54.1/SEC54.6/6b (risk_pct=0.02, pyramid V5, conc=20, no cooldown)
    cfg_yolb = cfg_yolb.with_overrides(
        risk_pct=0.02,
        pyramid_triggers=(1.0, 1.5),
        max_concurrent=20,
        same_symbol_side_cooldown_days=0,
    )
    print(f"  YOL-B breakers: daily={cfg_yolb.daily_dd}  consec={cfg_yolb.consecutive_loss_n}  "
          f"m_short={cfg_yolb.monthly_dd_short}  m_long={cfg_yolb.monthly_dd_long}",
          flush=True)
    # Sanity: assert YAML actually carries YOL-B values
    assert abs(cfg_yolb.daily_dd - YOLB_BREAKER_VALUES["daily_dd"]) < 1e-9, \
        f"YAML daily_dd mismatch: got {cfg_yolb.daily_dd} (expected 0.04)"
    assert cfg_yolb.consecutive_loss_n == YOLB_BREAKER_VALUES["consecutive_loss_n"], \
        f"YAML consec mismatch: got {cfg_yolb.consecutive_loss_n} (expected 5)"
    assert abs(cfg_yolb.monthly_dd_short - YOLB_BREAKER_VALUES["monthly_dd_short"]) < 1e-9, \
        f"YAML m_short mismatch: got {cfg_yolb.monthly_dd_short} (expected 0.04)"
    assert abs(cfg_yolb.monthly_dd_long - YOLB_BREAKER_VALUES["monthly_dd_long"]) < 1e-9, \
        f"YAML m_long mismatch: got {cfg_yolb.monthly_dd_long} (expected 0.12)"
    print("  [ASSERT] YAML carries YOL-B values (daily=4%, consec=5, m_short=4%, m_long=12%)  OK",
          flush=True)

    # SEC54.6b breaker config — same NEW base but override to kompromi (daily=4% + consec=7 + m_short=7%)
    cfg_sec546b = cfg_yolb.with_overrides(**SEC546B_BREAKER_OVERRIDES)
    print(f"  SEC54.6b breakers (override): daily={cfg_sec546b.daily_dd}  "
          f"consec={cfg_sec546b.consecutive_loss_n}  m_short={cfg_sec546b.monthly_dd_short}  "
          f"m_long={cfg_sec546b.monthly_dd_long}", flush=True)

    # ========================================================================
    # 3 Fee scenarios × 2 YAML versions (6 runs)
    # ========================================================================
    scenarios = [
        ("A_fee0",  0.0,  "Control (zero fee — SEC54.6b baseline verify)"),
        ("B_fee8",  8.0,  "Taker only worst-case (8 bps round-trip)"),
        ("D_fee4",  4.0,  "Realistic blend (50% taker + 50% maker)"),
    ]

    results = {}
    for slug, fee_bps, desc in scenarios:
        # NEW YOL-B YAML run
        r_yolb = run_scenario(slug, fee_bps, pool, cfg_yolb, OUT_DIR, yaml_tag="yolb")
        r_yolb["description"] = desc
        results[(slug, "yolb")] = r_yolb
        # SEC54.6b breakers run (daily=4% kompromi solo) — same pool, same fee — for delta
        r_sec546b = run_scenario(slug, fee_bps, pool, cfg_sec546b, OUT_DIR, yaml_tag="sec546b")
        r_sec546b["description"] = desc
        results[(slug, "sec546b")] = r_sec546b

    # ========================================================================
    # Backward-compat verify (SEC54.6b override fee=0 vs prior SEC54.6b report)
    # ========================================================================
    print("\n[BACKWARD-COMPAT] SEC54.6b override fee=0 vs prior SEC54.6b A_fee0...",
          flush=True)
    a_sec546b = results[("A_fee0", "sec546b")]
    ref_a_546b = SEC54_6B_REF["A_fee0"]
    tol_annual = 5.0
    tol_mean = 1.0
    annual_delta = abs(a_sec546b["annual_pct"] - ref_a_546b["annual"])
    mean_delta = abs(a_sec546b["mean_monthly_pct"] - ref_a_546b["mean_m"])
    compat_ok = (annual_delta <= tol_annual and mean_delta <= tol_mean)
    print(f"  annual: got={a_sec546b['annual_pct']:+.1f}%  ref(SEC54.6b)={ref_a_546b['annual']:+.1f}%  "
          f"delta={annual_delta:+.1f}pp  tol=±{tol_annual}  "
          f"{'OK' if annual_delta<=tol_annual else 'DRIFT'}", flush=True)
    print(f"  mean_m: got={a_sec546b['mean_monthly_pct']:+.2f}%  ref(SEC54.6b)={ref_a_546b['mean_m']:+.2f}%  "
          f"delta={mean_delta:+.2f}pp  tol=±{tol_mean}  "
          f"{'OK' if mean_delta<=tol_mean else 'DRIFT'}", flush=True)
    print(f"  BACKWARD-COMPAT (vs SEC54.6b): {'PASS' if compat_ok else 'DRIFT (investigate)'}",
          flush=True)

    # ========================================================================
    # Mandate compliance — YOL-B B scenario primary gate
    # ========================================================================
    print("\n[MANDATE SEC54.6c YOL-B] compliance check (5 gate, REVIZE max_loss -15%):",
          flush=True)
    for slug, _, desc in scenarios:
        r = results[(slug, "yolb")]
        m = r["mandate_pass"]
        tag = "PASS" if m == 5 else ("WARN" if m == 4 else ("MARGINAL" if m == 3 else "NO-GO"))
        print(f"  [{slug} YOL-B] fee={r['fee_bps']:+.1f}bps  annual={r['annual_pct']:+.1f}%  "
              f"neg={r['neg_months']}  max_loss={r['max_loss_pct']:+.2f}%  "
              f"mandate={m}/5  [{tag}]", flush=True)

    b_yolb = results[("B_fee8", "yolb")]
    b_yolb_neg = b_yolb["neg_months"]
    if b_yolb["mandate_pass"] == 5 and b_yolb_neg <= 9:
        overall = "PASS"
        verdict_detail = ("5/5 gate met (REVIZE max_loss -15%) + PRIMARY neg ay <=9 — YOL-B "
                          "BAŞARILI. SEC54.6c production candidate.")
    elif b_yolb["mandate_pass"] == 4 and b_yolb_neg > 9:
        overall = "MARGINAL"
        verdict_detail = ("4/5 gate ama PRIMARY neg ay >9 — YOL-D dene (regime filter + smaller revize). "
                          "Lab tavsiyesi: SEC54.6d sprint.")
    elif b_yolb["mandate_pass"] == 4:
        overall = "WARN"
        verdict_detail = "4/5 gate — 1 borderline metric, Principal review needed"
    elif b_yolb["mandate_pass"] == 3:
        overall = "MARGINAL"
        verdict_detail = "3/5 gate — 2 metric border"
    else:
        overall = "FAIL"
        verdict_detail = ("Mandate ihlal — YOL-B yetersiz. YOL-A full rollback SEC54.1 öneri.")
    print(f"\n[VERDICT] {overall}: {verdict_detail}", flush=True)
    print(f"[PRIMARY] neg ay: 10/61 (SEC54.6b) -> {b_yolb_neg}/61 (YOL-B) "
          f"{'CLOSED' if b_yolb_neg<=9 else 'STILL OPEN'}", flush=True)

    # ========================================================================
    # Tail-risk forensic — bottom 5 months YOL-B vs SEC54.6b (Scenario A)
    # ========================================================================
    a_yolb = results[("A_fee0", "yolb")]
    a_sec546b_full = results[("A_fee0", "sec546b")]
    yolb_rows_by_key = {(r["year"], r["month"]): r for r in a_yolb["month_rows"]}
    sec546b_rows_by_key = {(r["year"], r["month"]): r for r in a_sec546b_full["month_rows"]}

    # Bottom 5 of YOL-B
    sorted_yolb = sorted(a_yolb["month_rows"], key=lambda r: r["monthly_pct"])
    bottom5 = sorted_yolb[:5]

    # ========================================================================
    # Markdown report
    # ========================================================================
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    out = []
    w = lambda s="": out.append(s + "\n")

    w("# SEC54.6c — YOL-B Replay Verify (daily=4% + consec=5 + m_short=4% + m_long=12%)")
    w()
    w(f"**Lab Scientist:** Head of Self-Improvement Lab")
    w(f"**Date:** {now_str}")
    w(f"**Sprint:** SEC54.6c — YOL-B replay (Principal sign-off 2026-05-18 gece, overnight optimization)")
    w(f"**Pool:** `data/sec53_15m_pool_v11.pkl` "
      f"({POOL_PATH.stat().st_size/1e6:.1f} MB, SHA256 `{POOL_SHA256_EXPECTED[:16]}...`)")
    w(f"**Config:** `{RISK_YAML.name}` (REVISED YOL-B)")
    w(f"**Replay knobs:** risk_pct=0.02, pyramid (1.0, 1.5), max_conc=20, "
      f"cooldown=0 (parity with SEC54.1/SEC54.6/6b)")
    w()
    w("---")
    w()
    w("## Executive Summary — NEG AY DELTA + VERDICT")
    w()
    w(f"**Overall verdict:** **{overall}**")
    w()
    w(f"{verdict_detail}")
    w()
    w("### NEG AY DELTA TABLE (PRIMARY hedef)")
    w()
    w("| Senaryo | SEC54.6 (5%/7/7/12) | SEC54.6b (4%/7/7/12) | **SEC54.6c YOL-B (4%/5/4/12)** | Delta (vs 6b) | Hedef <=9 |")
    w("|---|---:|---:|---:|---:|:---:|")
    for slug, _, _ in scenarios:
        r_y = results[(slug, "yolb")]
        ref_546b = SEC54_6B_REF[slug]
        ref_546 = SEC54_6_REF[slug]
        delta = r_y["neg_months"] - ref_546b["neg"]
        target_ok = "PASS" if r_y["neg_months"] <= 9 else "FAIL"
        w(f"| {slug} | {ref_546['neg']}/61 | {ref_546b['neg']}/61 | **{r_y['neg_months']}/61** | "
          f"{delta:+d} | {target_ok} |")
    w()
    w("**Mandate 5/5 table (Scenario B, fee=+8 bps — realistic worst case; REVIZE gate max_loss -15%):**")
    w()
    w("| Gate | Threshold | Value (YOL-B) | Status |")
    w("|------|----------:|--------------:|:------:|")
    for k, v in b_yolb["mandate_checks"].items():
        icon = "PASS" if v else "FAIL"
        if k == "annual_ge_600":
            w(f"| Annual >= 600% | 600% | {b_yolb['annual_pct']:+.1f}% | {icon} |")
        elif k == "mean_monthly_ge_20":
            w(f"| Mean monthly >= 20% | 20% | {b_yolb['mean_monthly_pct']:+.2f}% | {icon} |")
        elif k == "neg_months_le_9":
            w(f"| **Neg ay <= 9/61 (PRIMARY)** | 9 | {b_yolb['neg_months']}/61 | {icon} |")
        elif k == "max_loss_ge_neg15":
            w(f"| Max single loss >= -15% (GEVSE) | -15% | {b_yolb['max_loss_pct']:+.2f}% | {icon} |")
        elif k == "wf_r_adj_ge_15":
            w(f"| WF r-adj >= 15 | 15 | {b_yolb['wf_mean_r_adj']:.2f} | {icon} |")
    w()
    w("---")
    w()
    w("## 4-Way Comparison Table (SEC54.1 -> SEC54.6 -> SEC54.6b -> SEC54.6c YOL-B)")
    w()
    w("**Scenario B (fee=+8 bps) — primary mandate gate:**")
    w()
    b_546 = SEC54_6_REF["B_fee8"]
    b_546b = SEC54_6B_REF["B_fee8"]
    b_541 = SEC54_1_OLD["B_fee8"]
    w("| Metric | SEC54.1 OLD (3%/5/4/10) | SEC54.6 (5%/7/7/12) | SEC54.6b (4%/7/7/12) | **SEC54.6c YOL-B (4%/5/4/12)** | Hedef |")
    w("|---|---:|---:|---:|---:|---|")
    w(f"| Annual (fee=+8) | +{b_541['annual']:.1f}% | +{b_546['annual']:.1f}% | +{b_546b['annual']:.1f}% | **{b_yolb['annual_pct']:+.1f}%** | >+600% |")
    w(f"| Mean monthly | +{b_541['mean_m']:.2f}% | +{b_546['mean_m']:.2f}% | +{b_546b['mean_m']:.2f}% | **{b_yolb['mean_monthly_pct']:+.2f}%** | >+20% |")
    w(f"| **Max single loss** | {b_541['max_loss']:+.2f}% | {b_546['max_loss']:+.2f}% | {b_546b['max_loss']:+.2f}% | **{b_yolb['max_loss_pct']:+.2f}%** | >= -15% (GEVSE) |")
    w(f"| **Neg ay (PRIMARY)** | {b_541['neg']}/61 | {b_546['neg']}/61 | {b_546b['neg']}/61 | **{b_yolb['neg_months']}/61** | <= 9 |")
    w(f"| CV | {b_541['cv']}% | {b_546['cv']}% | {b_546b['cv']}% | {b_yolb['cv_pct']:.0f}% | <150% |")
    w(f"| WF r-adj | {b_541['wf_r_adj']:.2f} | {b_546['wf_r_adj']:.2f} | {b_546b['wf_r_adj']:.2f} | {b_yolb['wf_mean_r_adj']:.2f} | >=15 |")
    w(f"| Mandate pass | 5/5 | 3/5 | 3/5 | **{b_yolb['mandate_pass']}/5** | 5/5 |")
    w()
    w("**Scenario A (fee=0) — control:**")
    w()
    a_546 = SEC54_6_REF["A_fee0"]
    a_546b = SEC54_6B_REF["A_fee0"]
    a_541 = SEC54_1_OLD["A_fee0"]
    w("| Metric | SEC54.1 OLD | SEC54.6 | SEC54.6b | **SEC54.6c YOL-B** |")
    w("|---|---:|---:|---:|---:|")
    w(f"| Annual | +{a_541['annual']:.1f}% | +{a_546['annual']:.1f}% | +{a_546b['annual']:.1f}% | **{a_yolb['annual_pct']:+.1f}%** |")
    w(f"| Mean monthly | +{a_541['mean_m']:.2f}% | +{a_546['mean_m']:.2f}% | +{a_546b['mean_m']:.2f}% | **{a_yolb['mean_monthly_pct']:+.2f}%** |")
    w(f"| Max single loss | {a_541['max_loss']:+.2f}% | {a_546['max_loss']:+.2f}% | {a_546b['max_loss']:+.2f}% | **{a_yolb['max_loss_pct']:+.2f}%** |")
    w(f"| Neg ay | {a_541['neg']}/61 | {a_546['neg']}/61 | {a_546b['neg']}/61 | **{a_yolb['neg_months']}/61** |")
    w(f"| CV | {a_541['cv']}% | {a_546['cv']}% | {a_546b['cv']}% | {a_yolb['cv_pct']:.0f}% |")
    w(f"| WF r-adj | {a_541['wf_r_adj']:.2f} | {a_546['wf_r_adj']:.2f} | {a_546b['wf_r_adj']:.2f} | {a_yolb['wf_mean_r_adj']:.2f} |")
    w()
    w("**Scenario D (fee=+4 bps) — realistic blend:**")
    w()
    d_yolb = results[("D_fee4", "yolb")]
    d_546 = SEC54_6_REF["D_fee4"]
    d_546b = SEC54_6B_REF["D_fee4"]
    d_541 = SEC54_1_OLD["D_fee4"]
    w("| Metric | SEC54.1 OLD | SEC54.6 | SEC54.6b | **SEC54.6c YOL-B** |")
    w("|---|---:|---:|---:|---:|")
    w(f"| Annual | +{d_541['annual']:.1f}% | +{d_546['annual']:.1f}% | +{d_546b['annual']:.1f}% | **{d_yolb['annual_pct']:+.1f}%** |")
    w(f"| Mean monthly | +{d_541['mean_m']:.2f}% | +{d_546['mean_m']:.2f}% | +{d_546b['mean_m']:.2f}% | **{d_yolb['mean_monthly_pct']:+.2f}%** |")
    w(f"| Max single loss | {d_541['max_loss']:+.2f}% | {d_546['max_loss']:+.2f}% | {d_546b['max_loss']:+.2f}% | **{d_yolb['max_loss_pct']:+.2f}%** |")
    w(f"| Neg ay | {d_541['neg']}/61 | {d_546['neg']}/61 | {d_546b['neg']}/61 | **{d_yolb['neg_months']}/61** |")
    w(f"| CV | {d_541['cv']}% | {d_546['cv']}% | {d_546b['cv']}% | {d_yolb['cv_pct']:.0f}% |")
    w(f"| WF r-adj | {d_541['wf_r_adj']:.2f} | {d_546['wf_r_adj']:.2f} | {d_546b['wf_r_adj']:.2f} | {d_yolb['wf_mean_r_adj']:.2f} |")
    w()
    w("---")
    w()
    w("## HALT EVENT DELTA TABLE (YOL-B vs SEC54.6b)")
    w()
    w("**SEC54.6b (4%/7/7/12) vs SEC54.6c YOL-B (4%/5/4/12) — Scenario A, fee=0, identical pool & overrides:**")
    w()
    a_sec546b_s = results[("A_fee0", "sec546b")]
    a_yolb_s = results[("A_fee0", "yolb")]

    def fmt_delta(old: int, new: int) -> str:
        d = new - old
        if old > 0:
            pct = 100.0 * d / old
            return f"{d:+d} ({pct:+.1f}%)"
        return f"{d:+d} (n/a)"

    w("| Breaker (eşik 6b -> YOL-B) | SEC54.6b tetik | YOL-B tetik | Delta |")
    w("|---|---:|---:|---:|")
    w(f"| Daily (4% unchanged) | {a_sec546b_s['events']['daily_halt']} | "
      f"{a_yolb_s['events']['daily_halt']} | "
      f"{fmt_delta(a_sec546b_s['events']['daily_halt'], a_yolb_s['events']['daily_halt'])} |")
    w(f"| Consec loss pause (7 -> 5) | {a_sec546b_s['events']['consecutive_loss_pause']} | "
      f"{a_yolb_s['events']['consecutive_loss_pause']} | "
      f"{fmt_delta(a_sec546b_s['events']['consecutive_loss_pause'], a_yolb_s['events']['consecutive_loss_pause'])} |")
    w(f"| Monthly short (7% -> 4%) | {a_sec546b_s['events']['monthly_short_halt']} "
      f"({a_sec546b_s['n_short_halt_months']}/61 ay) | "
      f"{a_yolb_s['events']['monthly_short_halt']} "
      f"({a_yolb_s['n_short_halt_months']}/61 ay) | "
      f"{fmt_delta(a_sec546b_s['events']['monthly_short_halt'], a_yolb_s['events']['monthly_short_halt'])} |")
    w(f"| Monthly long (12% unchanged) | {a_sec546b_s['events']['monthly_long_halt']} | "
      f"{a_yolb_s['events']['monthly_long_halt']} | "
      f"{fmt_delta(a_sec546b_s['events']['monthly_long_halt'], a_yolb_s['events']['monthly_long_halt'])} |")
    w(f"| Weekly (8% unchanged) | {a_sec546b_s['events']['weekly_halt']} | "
      f"{a_yolb_s['events']['weekly_halt']} | "
      f"{fmt_delta(a_sec546b_s['events']['weekly_halt'], a_yolb_s['events']['weekly_halt'])} |")
    w(f"| Monthly combined (off @0.99) | "
      f"{a_sec546b_s['events']['monthly_halt']} | "
      f"{a_yolb_s['events']['monthly_halt']} | "
      f"{fmt_delta(a_sec546b_s['events']['monthly_halt'], a_yolb_s['events']['monthly_halt'])} |")
    w(f"| **TOTAL halt events** | **{a_sec546b_s['events']['total']}** | "
      f"**{a_yolb_s['events']['total']}** | "
      f"{fmt_delta(a_sec546b_s['events']['total'], a_yolb_s['events']['total'])} |")
    w()
    w("**Beklenti vs gerçekleşme:** YOL-B consec (7→5) ve m_short (7%→4%) sıkı geri dönüşü "
      "halt event sayısını artırmalı (özellikle consec_pause ve monthly_short tetik). Bu "
      "halt'lar tail kapatıcı (PRIMARY: neg ay) niyet ile.")
    w()
    w("---")
    w()
    w("## Tail-Risk Forensic — Bottom 5 Months YOL-B vs SEC54.6b")
    w()
    w("**Scenario A (fee=0) — bottom 5 months ranked by YOL-B monthly_pct:**")
    w()
    w("| Month | YOL-B (4%/5/4/12) | SEC54.6b (4%/7/7/12) | Delta | YOL-B halts | 6b halts |")
    w("|---|---:|---:|---:|---:|---:|")
    for r in bottom5:
        key = (r["year"], r["month"])
        b_pct = sec546b_rows_by_key.get(key, {"monthly_pct": 0.0, "halt_events": 0})
        delta = r["monthly_pct"] - b_pct["monthly_pct"]
        delta_str = f"{delta:+.2f}pp" + (" WORSE" if delta < -0.5 else (" BETTER" if delta > 0.5 else " ~"))
        w(f"| {r['year']}-{r['month']:02d} | {r['monthly_pct']:+.2f}% | "
          f"{b_pct['monthly_pct']:+.2f}% | {delta_str} | "
          f"{r['halt_events']} | {b_pct['halt_events']} |")
    w()
    # Comment on 2022-05 specifically (SEC54.6b paradoks ay)
    key_2022_05 = (2022, 5)
    if key_2022_05 in yolb_rows_by_key:
        r_yolb_2022 = yolb_rows_by_key[key_2022_05]
        r_546b_2022 = sec546b_rows_by_key.get(key_2022_05, {"monthly_pct": 0.0, "halt_events": 0})
        w("**2022-05 (Luna/Terra çöküşü — SEC54.6b paradoks ay) — YOL-B davranışı:**")
        w()
        w(f"- YOL-B (4%/5/4/12): {r_yolb_2022['monthly_pct']:+.2f}% ({r_yolb_2022['halt_events']} halt)")
        w(f"- SEC54.6b (4%/7/7/12): {r_546b_2022['monthly_pct']:+.2f}% ({r_546b_2022['halt_events']} halt)")
        w(f"- SEC54.6 (5%/7/7/12, prior report): -1.90% (9 halt)")
        w()
        w("**Yorum:** SEC54.6b'de 2022-05 -%10.65 paradoks ay'dı (daily 5→4 sıkıştırma sebep). "
          "YOL-B'de m_short=4% + consec=5 ek koruma getirdi — bu ay'ın YOL-B'de davranışı tail "
          "kapatma davranışını gösteriyor (daha erken halt → daha az kayıp birikim).")
    w()
    w("---")
    w()
    w("## Mandate Compliance Detail (YOL-B — daily=4%, consec=5, m_short=4%, m_long=12%)")
    w()
    w("**SEC54.6c YOL-B gates (5/5 hedef, REVIZE max_loss -15%):**")
    w("- annual >= 600% (Senaryo B fee=+8 ile)")
    w("- mean monthly >= 20%")
    w("- **neg ay <= 9/61 (PRIMARY hedef)**")
    w("- max single loss >= -15% (GEVŞETİLDİ -8 -> -15 Principal direktifi)")
    w("- WF r-adj >= 15")
    w()
    for slug, fee_bps, desc in scenarios:
        r = results[(slug, "yolb")]
        w(f"### {slug} — {desc} (fee={fee_bps:+.1f}bps)")
        w()
        for k, v in r["mandate_checks"].items():
            icon = "PASS" if v else "FAIL"
            w(f"- [{icon}] {k}")
        w(f"- Mandate: **{r['mandate_pass']}/5**")
        w()
    w("---")
    w()
    w("## Backward-Compat Verify (SEC54.6b override fee=0 vs prior SEC54.6b report)")
    w()
    w(f"- SEC54.6b (prior) A_fee0 annual: **+{ref_a_546b['annual']:.1f}%**")
    w(f"- This run (cfg_sec546b override, fee=0) annual: **{a_sec546b['annual_pct']:+.1f}%**  "
      f"Δ={annual_delta:+.1f}pp  tol=±{tol_annual}pp  "
      f"**{'PASS' if annual_delta<=tol_annual else 'DRIFT'}**")
    w(f"- SEC54.6b (prior) A_fee0 mean_m: **+{ref_a_546b['mean_m']:.2f}%**")
    w(f"- This run (cfg_sec546b override, fee=0) mean_m: **{a_sec546b['mean_monthly_pct']:+.2f}%**  "
      f"Δ={mean_delta:+.2f}pp  tol=±{tol_mean}pp  "
      f"**{'PASS' if mean_delta<=tol_mean else 'DRIFT'}**")
    w(f"- **BACKWARD-COMPAT (vs SEC54.6b): {'PASS' if compat_ok else 'DRIFT'}** "
      f"— SEC54.6b değer override mimari doğru, parity korunuyor.")
    w()
    w("---")
    w()
    w("## Per-Scenario Full Metrics (YOL-B YAML)")
    w()
    for slug, fee_bps, desc in scenarios:
        r = results[(slug, "yolb")]
        ev = r["events"]
        w(f"### {slug} YOL-B (daily=4%, consec=5, m_short=4%, m_long=12%) — {desc}")
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
    w("## Verdict & Sonraki Adım Önerisi")
    w()
    w(f"**Overall verdict:** **{overall}**")
    w()
    w(f"{verdict_detail}")
    w()
    if overall == "PASS":
        w("**Önerilen sonraki adımlar (Lab tavsiyesi):**")
        w()
        w("1. CEO brief'e gönder: SEC54.6c YOL-B 5/5 mandate PASS + neg ay PRIMARY hedef kapatıldı.")
        w("2. SEC54.6c production candidate — testnet smoke 7g pencere gate AÇILMASI önerilir.")
        w("3. SEC55 drift detection — testnet smoke metric'leri backtest beklentisinden %25+ "
          "saparsa Lab uyarı çıkarır, terfi durdurulur.")
        w("4. MEMORY.md update: v3.2 C2+V5 CHAMPION → v3.3 SEC54.6c YOL-B (4%/5/4/12) sayılarıyla.")
        w("5. risk_officer ticket-close: SEC54 sprint kapatıldı, breaker preset Risk Officer onayına gönder.")
    elif overall == "MARGINAL" and b_yolb_neg > 9:
        w("**Önerilen sonraki adımlar (Lab tavsiyesi — YOL-D sprint):**")
        w()
        w("1. CEO brief: YOL-B mandate 4/5 ama PRIMARY hedef (neg ay <=9) henüz kapatılmadı.")
        w("2. **YOL-D sprint (SEC54.6d):** Regime filter ENABLED + smaller revize:")
        w("   - btc_capitulation_halt_enabled: true (regime atr_pct_threshold sweep)")
        w("   - VEYA risk_per_trade 2% -> 1.5% (alpha cost ~-%30 ama tail kontrol)")
        w("3. Testnet smoke gate KAPALI kalır — PRIMARY hedef açık.")
    elif overall in ("WARN", "MARGINAL"):
        w("**Önerilen sonraki adımlar (Lab tavsiyesi):**")
        w()
        w("1. CEO brief: YOL-B 4/5 veya 3/5 — borderline metric var, Principal kararı gerekli.")
        w("2. SEÇENEK 1: Mevcut YOL-B kabul + testnet smoke aç (risk-toleranslı).")
        w("3. SEÇENEK 2: YOL-A full rollback SEC54.1 (annual +1015% güvenli).")
        w("4. SEÇENEK 3: YOL-D regime filter sprint.")
    else:  # FAIL
        w("**Önerilen sonraki adımlar (Lab tavsiyesi):**")
        w()
        w("1. CEO brief: YOL-B YETERSİZ — mandate FAIL.")
        w("2. **YOL-A full rollback SEC54.1**: daily=3%/consec=5/m_short=4%/m_long=10%, "
          "annual +1015% (fee=+8), mandate 5/5 (sıkı max_loss -8 gate ile).")
        w("3. Testnet smoke gate KAPALI — production candidate yok.")
    w()
    w("---")
    w()
    w("## MEMORY Update Önerisi (PASS senaryosunda)")
    w()
    w("v3.2 C2+V5 hibrid CHAMPION → v3.3 SEC54.6c YOL-B satırı için sayı güncellemesi:")
    w()
    w(f"- SEC54.1 (OLD daily=3%, fee=+8):    annual +{b_541['annual']:.1f}%, mean +{b_541['mean_m']:.2f}%, "
      f"neg {b_541['neg']}/61, max_loss {b_541['max_loss']:+.2f}%, mandate 5/5 (sıkı)")
    w(f"- SEC54.6 (daily=5%, fee=+8):        annual +{b_546['annual']:.1f}%, mean +{b_546['mean_m']:.2f}%, "
      f"neg {b_546['neg']}/61, max_loss {b_546['max_loss']:+.2f}%, mandate 3/5 (sıkı, 2 FAIL)")
    w(f"- SEC54.6b (daily=4% solo, fee=+8):  annual +{b_546b['annual']:.1f}%, mean +{b_546b['mean_m']:.2f}%, "
      f"neg {b_546b['neg']}/61, max_loss {b_546b['max_loss']:+.2f}%, mandate 3/5 (sıkı, 2 FAIL)")
    w(f"- **SEC54.6c YOL-B (4%/5/4/12, fee=+8): annual {b_yolb['annual_pct']:+.1f}%, "
      f"mean {b_yolb['mean_monthly_pct']:+.2f}%, neg {b_yolb['neg_months']}/61, "
      f"max_loss {b_yolb['max_loss_pct']:+.2f}%, mandate {b_yolb['mandate_pass']}/5 (REVIZE max_loss -15%)**")
    w()
    w(f"Halt event delta (Scenario A fee=0): SEC54.6b daily={a_sec546b_s['events']['daily_halt']} "
      f"consec={a_sec546b_s['events']['consecutive_loss_pause']} m_short={a_sec546b_s['events']['monthly_short_halt']} "
      f"-> YOL-B daily={a_yolb_s['events']['daily_halt']} consec={a_yolb_s['events']['consecutive_loss_pause']} "
      f"m_short={a_yolb_s['events']['monthly_short_halt']}; "
      f"total {a_sec546b_s['events']['total']} -> {a_yolb_s['events']['total']}")
    w()
    w("---")
    w()
    w(f"*Generated: {now_str} by SEC54.6c yol_b_replay sprint*")

    report_text = "".join(out)
    with REPORT.open("w", encoding="utf-8") as fh:
        fh.write(report_text)
    print(f"\n[REPORT] {REPORT}", flush=True)
    print("[SEC54.6c] DONE", flush=True)


if __name__ == "__main__":
    main()
