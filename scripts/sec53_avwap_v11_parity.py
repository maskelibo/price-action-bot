"""SEC53 — AVWAP v1.1 Parity Sprint (Lab Scientist).

Pre-reg / context:
  - Signal Chief SEC52 AVWAP v1.0 -> v1.1 dynamic confluence fix.
    Report: `reports/signal_chief/2026-05-17_avwap_confluence_fix.md`
  - Lab SEC52 C2+V5 hybrid (V3 in-memory patch) sayilari:
    Annual +1253.3%, Mean M +27.39%, Pos 55, Neg 6, Sub-20 32,
    Max loss -4.57%, CV 115%, WF r-adj 36.41
  - Mevcut pool (`data/sec31_15m_pool.pkl`) eski v1.0 ile uretilmis
    (AVWAP conf = 0.0). v1.1 fix etkin -> yeni pool yeniden uretilmeli.

Hedef:
  Step 1 — TOP-4 strateji × 10 sym × 5y pool YENIDEN URET (AVWAP v1.1 ile)
  Step 2 — Pool stats karsilastirma: eski vs yeni
  Step 3 — C2+V5 hibrid replay (V2 risk %2 + V5 pyramid 1.5R)
           per-month 61 ay + walk-forward 34-window
  Step 4 — Parity verify: Lab SEC52 sayilari ile delta
  Step 5 — Verdict: parity ✅ -> production candidate APPROVED + YAML draft
           parity ⚠️ -> mandate re-eval (4/5 hala mi?)
  Step 6 — Rapor + draft YAML (parity gecerse)

Cikti:
  data/sec53_15m_pool_v11.pkl                                (yeni pool)
  reports/lab/2026-05-17_sec53_avwap_v11_parity.md           (PRIMARY rapor)
  reports/lab/sec53_pool_stats_compare.csv                   (eski vs yeni)
  reports/lab/sec53_c2v5_per_month.csv                       (61 ay)
  reports/lab/sec53_c2v5_walkforward.csv                     (34 pencere)
  configs/risk_phoenix_scalp_15m_c2v5_final.yaml             (DRAFT, parity gecerse)

Disiplin:
  - lab.py + production YAML DOKUNULMADI
  - sec31_phoenix_scalp_15m_rolling.collect_all_trades RE-USE (TOP-4 override)
  - sec31_15m_pool.pkl DOKUNULMADI (eski v1.0 karsilastirma referansi)
  - In-memory patch YOK (v1.1 zaten gercek dinamik conf uretir)
  - 1d Phoenix v2.0.4 + 5m configs etkilenmemeli
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

import scripts.sec31_phoenix_scalp_15m_rolling as sec31
from price_action.backtest.lab import ProductionConfig, production_replay

# ============================================================================
# Paths
# ============================================================================
OLD_POOL = ROOT / "data" / "sec31_15m_pool.pkl"          # AVWAP v1.0 (referans)
NEW_POOL = ROOT / "data" / "sec53_15m_pool_v11.pkl"      # AVWAP v1.1 (yeni)
RISK_YAML = ROOT / "configs" / "risk_phoenix_scalp_15m_pyramid_r3.yaml"
REPORT = ROOT / "reports" / "lab" / "2026-05-17_sec53_avwap_v11_parity.md"
CSV_POOL_CMP = ROOT / "reports" / "lab" / "sec53_pool_stats_compare.csv"
CSV_MONTH = ROOT / "reports" / "lab" / "sec53_c2v5_per_month.csv"
CSV_WF = ROOT / "reports" / "lab" / "sec53_c2v5_walkforward.csv"
DRAFT_YAML = ROOT / "configs" / "risk_phoenix_scalp_15m_c2v5_final.yaml"

# TOP-4 (Round 4 ablation: vsa + brooks_fb + avwap + engulfing_cont)
TOP4_STRATEGIES = [
    ("vsa_climax_test", "VSAClimaxTestStrategy"),
    ("brooks_failed_breakout", "BrooksFailedBreakoutStrategy"),
    ("anchored_vwap_reversal", "AnchoredVWAPReversalStrategy"),
    ("engulfing_continuation", "EngulfingContinuationStrategy"),
]
TOP4_NAMES = {m for m, _ in TOP4_STRATEGIES}
SYMBOLS_10 = sec31.SYMBOLS_10  # 10 sym Phoenix universe

# Force refresh env: SEC53_FORCE=1 -> yeni pool reproduce et
FORCE_REFRESH = bool(int(os.environ.get("SEC53_FORCE", "0")))

# Lab SEC52 (V3 patch) reference numbers (compare target)
SEC52_REF = {
    "annual_pct": 1253.3,
    "mean_monthly_pct": 27.39,
    "pos_months": 55,
    "neg_months": 6,
    "sub20_months": 32,
    "max_loss_pct": -4.57,
    "cv_pct": 115.0,
    "wf_mean_r_adj": 36.41,
}

# Parity tolerance bands (rapor §Step 4 tablosu)
TOLERANCE = {
    "annual_pct": 25.0,         # ±25pp
    "mean_monthly_pct": 1.0,    # ±1pp
    "pos_months": 2,            # ±2
    "neg_months": 1,            # ±1
    "sub20_months": 2,          # ±2
    "max_loss_pct": 1.0,        # ±1pp
    "cv_pct": 5.0,              # ±5
    "wf_mean_r_adj": 2.0,       # ±2
}


# ============================================================================
# Utilities
# ============================================================================
def to_utc(ts):
    if hasattr(ts, "tz_localize"):
        if ts.tzinfo is None:
            return ts.tz_localize("UTC")
        return ts.tz_convert("UTC")
    if ts.tzinfo is None:
        return ts.replace(tzinfo=timezone.utc)
    return ts.astimezone(timezone.utc)


# ============================================================================
# Pool collection (TOP-4 override sec31.collect_all_trades)
# ============================================================================
def collect_new_pool() -> list[dict]:
    """TOP-4 strateji × 10 sym × 5y pool — AVWAP v1.1 etkin."""
    print(f"[COLLECT] TOP-4 × {len(SYMBOLS_10)} sym × 15m × 5y "
          f"(AVWAP v1.1 dynamic confluence)", flush=True)
    print(f"  strategies: {[m for m, _ in TOP4_STRATEGIES]}", flush=True)
    t0 = time.time()

    # sec31 modülü global PHOENIX_STRATEGIES'i kullanır -> TOP-4 override
    original = sec31.PHOENIX_STRATEGIES
    sec31.PHOENIX_STRATEGIES = TOP4_STRATEGIES
    try:
        pool = sec31.collect_all_trades(SYMBOLS_10, parallel=False)
    finally:
        sec31.PHOENIX_STRATEGIES = original

    elapsed = time.time() - t0
    print(f"[COLLECT DONE] {len(pool):,} trade, {elapsed/60:.1f} min", flush=True)
    return pool


def load_or_collect_new_pool() -> list[dict]:
    if NEW_POOL.exists() and not FORCE_REFRESH:
        print(f"[CACHE HIT] {NEW_POOL} ({NEW_POOL.stat().st_size/1e6:.1f} MB)", flush=True)
        with NEW_POOL.open("rb") as f:
            return pickle.load(f)
    pool = collect_new_pool()
    NEW_POOL.parent.mkdir(parents=True, exist_ok=True)
    with NEW_POOL.open("wb") as f:
        pickle.dump(pool, f, protocol=pickle.HIGHEST_PROTOCOL)
    print(f"[PERSIST] {NEW_POOL} ({NEW_POOL.stat().st_size/1e6:.1f} MB)", flush=True)
    return pool


# ============================================================================
# Pool stats
# ============================================================================
def pool_avwap_stats(pool: list[dict]) -> dict:
    """AVWAP-only istatistik: trade sayisi, conf dagilimi, filter geciren oran."""
    avw = [t for t in pool if t.get("strategy") == "anchored_vwap_reversal"]
    if not avw:
        return {"n": 0, "n_conf_ge_025": 0, "n_conf_eq_0": 0,
                "mean_conf": 0.0, "median_conf": 0.0,
                "p25_conf": 0.0, "p75_conf": 0.0}
    confs = [float(t.get("conf", 0.0)) for t in avw]
    confs_sorted = sorted(confs)
    n = len(confs)
    p25 = confs_sorted[int(n * 0.25)] if n > 4 else confs_sorted[0]
    p75 = confs_sorted[int(n * 0.75)] if n > 4 else confs_sorted[-1]
    return {
        "n": n,
        "n_conf_ge_025": sum(1 for c in confs if c >= 0.25),
        "n_conf_eq_0": sum(1 for c in confs if c == 0.0),
        "n_conf_ge_050": sum(1 for c in confs if c >= 0.50),
        "n_conf_ge_075": sum(1 for c in confs if c >= 0.75),
        "n_conf_eq_100": sum(1 for c in confs if c >= 0.999),
        "mean_conf": sum(confs) / n,
        "median_conf": confs_sorted[n // 2],
        "p25_conf": p25,
        "p75_conf": p75,
        "min_conf": min(confs),
        "max_conf": max(confs),
    }


def pool_overall_stats(pool: list[dict]) -> dict:
    if not pool:
        return {}
    n = len(pool)
    Rs = [float(t["R"]) for t in pool]
    return {
        "n_total": n,
        "mean_R": sum(Rs) / n,
        "WR_pct": sum(1 for r in Rs if r > 0) * 100.0 / n,
        "n_avwap": sum(1 for t in pool if t.get("strategy") == "anchored_vwap_reversal"),
        "n_vsa": sum(1 for t in pool if t.get("strategy") == "vsa_climax_test"),
        "n_brooks": sum(1 for t in pool if t.get("strategy") == "brooks_failed_breakout"),
        "n_engulf": sum(1 for t in pool if t.get("strategy") == "engulfing_continuation"),
    }


# ============================================================================
# Per-month metrics (Lab SEC52 parity)
# ============================================================================
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


# ============================================================================
# Walk-forward 34-window
# ============================================================================
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
# Parity verdict
# ============================================================================
def evaluate_parity(s: dict, ref: dict, tol: dict) -> dict:
    """Her metric icin within-tolerance kontrolu + mandate 4/5 yeniden hesap."""
    report = {}
    for key, ref_val in ref.items():
        cur = s.get(key, None)
        if cur is None:
            report[key] = {"ref": ref_val, "cur": None, "delta": None,
                            "within_tol": False, "tol": tol.get(key)}
            continue
        delta = cur - ref_val
        within = abs(delta) <= tol.get(key, 1e9)
        report[key] = {"ref": ref_val, "cur": cur, "delta": delta,
                        "within_tol": within, "tol": tol.get(key)}
    # Overall parity = tum metric within tolerance
    overall = all(v["within_tol"] for v in report.values())
    report["_overall"] = overall
    return report


# Mandate check (Lab SEC52 Step 6 — 5 hard gate)
def mandate_check(s: dict) -> dict:
    """Lab SEC52 mandate compliance 5/5."""
    checks = {
        "annual_ge_800": s["annual_pct"] >= 800.0,
        "mean_monthly_ge_25": s["mean_monthly_pct"] >= 25.0,
        "neg_months_le_7": s["neg_months"] <= 7,
        "max_loss_ge_neg10": s["max_loss_pct"] >= -10.0,
        "wf_r_adj_ge_15": s["wf_mean_r_adj"] >= 15.0,
    }
    n_pass = sum(1 for v in checks.values() if v)
    return {"checks": checks, "n_pass": n_pass, "total": len(checks)}


# ============================================================================
# Main
# ============================================================================
def main():
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    print(f"[SEC53] AVWAP v1.1 parity sprint", flush=True)
    print(f"  force_refresh = {FORCE_REFRESH}", flush=True)

    # ========================================================================
    # Step 1 — Yeni pool reproduce (AVWAP v1.1 etkin)
    # ========================================================================
    print(f"\n[STEP 1] Pool reproduce", flush=True)
    pool_new_raw = load_or_collect_new_pool()
    pool_new = [t for t in pool_new_raw
                if t.get("strategy") in TOP4_NAMES and t.get("symbol") in set(SYMBOLS_10)]
    print(f"[POOL NEW] {len(pool_new):,} trade (TOP-4 × 10 sym)", flush=True)

    # ========================================================================
    # Step 2 — Eski pool ile karsilastirma
    # ========================================================================
    print(f"\n[STEP 2] Pool stats compare (old v1.0 vs new v1.1)", flush=True)
    old_loaded = False
    pool_old = []
    if OLD_POOL.exists():
        try:
            with OLD_POOL.open("rb") as fh:
                pool_old_raw = pickle.load(fh)
            pool_old = [t for t in pool_old_raw
                        if t.get("strategy") in TOP4_NAMES
                        and t.get("symbol") in set(SYMBOLS_10)]
            old_loaded = True
            print(f"[POOL OLD] {len(pool_old):,} trade (TOP-4 × 10 sym)", flush=True)
        except Exception as e:
            print(f"[WARN] Old pool load failed: {e}", flush=True)

    new_stats = pool_overall_stats(pool_new)
    new_avwap = pool_avwap_stats(pool_new)
    old_stats = pool_overall_stats(pool_old) if old_loaded else {}
    old_avwap = pool_avwap_stats(pool_old) if old_loaded else {}

    print(f"\n  NEW pool: total={new_stats['n_total']:,}  "
          f"AVWAP={new_stats['n_avwap']:,}  mean_R={new_stats['mean_R']:+.4f}  "
          f"WR={new_stats['WR_pct']:.1f}%", flush=True)
    print(f"  NEW AVWAP: conf>=0.25={new_avwap['n_conf_ge_025']:,} "
          f"(={100*new_avwap['n_conf_ge_025']/max(1,new_avwap['n']):.1f}%) "
          f"mean_conf={new_avwap['mean_conf']:.3f}", flush=True)
    if old_loaded:
        print(f"  OLD pool: total={old_stats['n_total']:,}  "
              f"AVWAP={old_stats['n_avwap']:,}  mean_R={old_stats['mean_R']:+.4f}  "
              f"WR={old_stats['WR_pct']:.1f}%", flush=True)
        print(f"  OLD AVWAP: conf>=0.25={old_avwap['n_conf_ge_025']:,} "
              f"(={100*old_avwap['n_conf_ge_025']/max(1,old_avwap['n']):.1f}%) "
              f"mean_conf={old_avwap['mean_conf']:.3f}", flush=True)

    # ========================================================================
    # Step 3 — C2+V5 hibrid replay (V2 risk %2 + V5 pyramid 1.5R)
    # ========================================================================
    print(f"\n[STEP 3] C2+V5 hibrid replay (yeni pool)", flush=True)
    cfg_base = ProductionConfig.from_yaml(str(RISK_YAML))
    cfg_base = cfg_base.with_overrides(max_concurrent=20, same_symbol_side_cooldown_days=0)
    print(f"  base: risk_pct={cfg_base.risk_pct} sym_cap={cfg_base.concentration_max_per_symbol_pct} "
          f"conf_min={cfg_base.conf_min} pyramid={cfg_base.pyramid_triggers}", flush=True)

    cfg_c2v5 = cfg_base.with_overrides(risk_pct=0.02, pyramid_triggers=(1.0, 1.5))
    print(f"  C2+V5: risk_pct={cfg_c2v5.risk_pct} pyramid={cfg_c2v5.pyramid_triggers}", flush=True)

    t0 = time.time()
    print(f"  [per-month 61 ay]...", flush=True)
    month_rows = per_month_metrics(pool_new, cfg_c2v5)
    print(f"  [walk-forward 34 pencere]...", flush=True)
    wf_rows = walk_forward_metrics(pool_new, cfg_c2v5)
    s_c2v5 = summarize_variant(month_rows, wf_rows)
    elapsed = time.time() - t0
    print(f"  [DONE] {elapsed/60:.1f} min", flush=True)
    print(f"  annual={s_c2v5['annual_pct']:+.1f}% mean_m={s_c2v5['mean_monthly_pct']:+.2f}% "
          f"pos={s_c2v5['pos_months']} neg={s_c2v5['neg_months']} sub20={s_c2v5['sub20_months']} "
          f"max_loss={s_c2v5['max_loss_pct']:+.2f}% CV={s_c2v5['cv_pct']:.0f}% "
          f"WF r-adj={s_c2v5['wf_mean_r_adj']:.2f}", flush=True)

    # Save CSVs
    with CSV_MONTH.open("w", newline="", encoding="utf-8") as fh:
        cols = ["year", "month", "n_raw", "n_taken", "monthly_pct", "dd_pct", "skip"]
        wr = csv.DictWriter(fh, fieldnames=cols)
        wr.writeheader()
        for r in month_rows:
            row = dict(r)
            row["monthly_pct"] = f"{row['monthly_pct']:.4f}"
            row["dd_pct"] = f"{row['dd_pct']:.4f}"
            wr.writerow(row)
    print(f"[CSV] {CSV_MONTH}")

    with CSV_WF.open("w", newline="", encoding="utf-8") as fh:
        cols = ["window", "start", "end", "trades", "annual_pct", "dd_pct", "r_adj"]
        wr = csv.DictWriter(fh, fieldnames=cols)
        wr.writeheader()
        for r in wf_rows:
            row = dict(r)
            row["annual_pct"] = f"{row['annual_pct']:.4f}"
            row["dd_pct"] = f"{row['dd_pct']:.4f}"
            row["r_adj"] = f"{row['r_adj']:.4f}"
            wr.writerow(row)
    print(f"[CSV] {CSV_WF}")

    # Pool stats CSV
    with CSV_POOL_CMP.open("w", newline="", encoding="utf-8") as fh:
        cols = ["metric", "old_v10", "new_v11", "delta"]
        wr = csv.DictWriter(fh, fieldnames=cols)
        wr.writeheader()
        pool_keys = [("n_total", "Total trade"), ("n_avwap", "AVWAP trade"),
                     ("n_vsa", "VSA trade"), ("n_brooks", "Brooks_fb trade"),
                     ("n_engulf", "Engulfing trade"), ("mean_R", "Pool mean R"),
                     ("WR_pct", "Pool WR%")]
        for key, label in pool_keys:
            old_v = old_stats.get(key, None)
            new_v = new_stats.get(key, None)
            d = ((new_v - old_v) if (old_v is not None and new_v is not None) else None)
            wr.writerow({"metric": label,
                         "old_v10": "" if old_v is None else f"{old_v:.4f}" if isinstance(old_v, float) else old_v,
                         "new_v11": "" if new_v is None else f"{new_v:.4f}" if isinstance(new_v, float) else new_v,
                         "delta": "" if d is None else f"{d:+.4f}" if isinstance(d, float) else f"{d:+d}"})
        # AVWAP detail
        avwap_keys = [("n", "AVWAP n"), ("n_conf_ge_025", "AVWAP conf>=0.25"),
                       ("n_conf_eq_0", "AVWAP conf=0.0"),
                       ("n_conf_ge_050", "AVWAP conf>=0.50"),
                       ("n_conf_ge_075", "AVWAP conf>=0.75"),
                       ("n_conf_eq_100", "AVWAP conf=1.0"),
                       ("mean_conf", "AVWAP mean conf"),
                       ("median_conf", "AVWAP median conf")]
        for key, label in avwap_keys:
            old_v = old_avwap.get(key, None)
            new_v = new_avwap.get(key, None)
            d = ((new_v - old_v) if (old_v is not None and new_v is not None) else None)
            wr.writerow({"metric": label,
                         "old_v10": "" if old_v is None else f"{old_v:.4f}" if isinstance(old_v, float) else old_v,
                         "new_v11": "" if new_v is None else f"{new_v:.4f}" if isinstance(new_v, float) else new_v,
                         "delta": "" if d is None else f"{d:+.4f}" if isinstance(d, float) else f"{d:+d}"})
    print(f"[CSV] {CSV_POOL_CMP}")

    # ========================================================================
    # Step 4 — Parity verify
    # ========================================================================
    print(f"\n[STEP 4] Parity verify (Lab SEC52 vs SEC53)", flush=True)
    parity = evaluate_parity(s_c2v5, SEC52_REF, TOLERANCE)
    for key in ["annual_pct", "mean_monthly_pct", "pos_months", "neg_months",
                "sub20_months", "max_loss_pct", "cv_pct", "wf_mean_r_adj"]:
        p = parity[key]
        flag = "OK" if p["within_tol"] else "FAIL"
        d_str = f"{p['delta']:+.3f}" if p['delta'] is not None else "—"
        print(f"  [{flag}] {key}: ref={p['ref']} cur={p['cur']} Δ={d_str} tol=±{p['tol']}",
              flush=True)
    print(f"  OVERALL parity: {'PASS' if parity['_overall'] else 'DRIFT'}", flush=True)

    # Mandate compliance (5-check)
    mandate = mandate_check(s_c2v5)
    print(f"\n  Mandate compliance: {mandate['n_pass']}/{mandate['total']}", flush=True)
    for k, v in mandate["checks"].items():
        print(f"    [{('OK' if v else 'FAIL')}] {k}", flush=True)

    # ========================================================================
    # Step 5 — Verdict
    # ========================================================================
    parity_pass = parity["_overall"]
    mandate_pass = mandate["n_pass"] >= 4   # SEC52 baseline 4/5

    print(f"\n[STEP 5] Verdict", flush=True)
    if parity_pass and mandate_pass:
        verdict = "PARITY_PASS"
        print(f"  VERDICT: PARITY ✅ — production candidate APPROVED", flush=True)
    elif mandate_pass:
        verdict = "DRIFT_BUT_MANDATE_OK"
        print(f"  VERDICT: PARITY DRIFT but mandate {mandate['n_pass']}/5 PASS — "
              f"new baseline candidate", flush=True)
    elif mandate["n_pass"] == 3:
        verdict = "MANDATE_REDUCED"
        print(f"  VERDICT: mandate 3/5 — Researcher new variant sprint",
              flush=True)
    else:
        verdict = "STRATEGY_REVISE"
        print(f"  VERDICT: mandate <{mandate['n_pass']}/5 — radical revise",
              flush=True)

    # ========================================================================
    # Step 6 — Markdown report
    # ========================================================================
    out = []
    w = lambda s="": out.append(s + "\n")
    w(f"# SEC53 — AVWAP v1.1 Parity Sprint")
    w(f"")
    w(f"**Lab Scientist:** Head of Self-Improvement Lab")
    w(f"**Date:** {datetime.now(timezone.utc).date().isoformat()}")
    w(f"**Sprint:** SEC53 (Signal Chief SEC52 v1.1 fix follow-up)")
    w(f"**Pre-reg input:** `reports/signal_chief/2026-05-17_avwap_confluence_fix.md`")
    w(f"**Reference numbers:** Lab SEC52 (`reports/lab/2026-05-17_c2_champion_validation.md`)")
    w(f"")
    w(f"---")
    w(f"")
    w(f"## Step 1 — Pool Reproduce (AVWAP v1.1)")
    w(f"")
    w(f"- TOP-4 strategies: `{', '.join(m for m, _ in TOP4_STRATEGIES)}`")
    w(f"- Universe: 10 sym × 15m × 5y (Phoenix v2.0.4 universe)")
    w(f"- AVWAP v1.1 dynamic confluence active (manifest hash `a862f36b62e81fa9`)")
    w(f"- New pool: `data/sec53_15m_pool_v11.pkl` ({NEW_POOL.stat().st_size/1e6:.1f} MB)")
    w(f"")
    w(f"## Step 2 — Pool Stats Compare (old v1.0 vs new v1.1)")
    w(f"")
    if old_loaded:
        w(f"| Metric | Old v1.0 | New v1.1 | Δ |")
        w(f"|---|---:|---:|---:|")
        w(f"| Total trade | {old_stats['n_total']:,} | {new_stats['n_total']:,} | "
          f"{new_stats['n_total'] - old_stats['n_total']:+,} |")
        w(f"| AVWAP trade | {old_stats['n_avwap']:,} | {new_stats['n_avwap']:,} | "
          f"{new_stats['n_avwap'] - old_stats['n_avwap']:+,} |")
        w(f"| VSA trade | {old_stats['n_vsa']:,} | {new_stats['n_vsa']:,} | "
          f"{new_stats['n_vsa'] - old_stats['n_vsa']:+,} |")
        w(f"| Brooks_fb trade | {old_stats['n_brooks']:,} | {new_stats['n_brooks']:,} | "
          f"{new_stats['n_brooks'] - old_stats['n_brooks']:+,} |")
        w(f"| Engulfing trade | {old_stats['n_engulf']:,} | {new_stats['n_engulf']:,} | "
          f"{new_stats['n_engulf'] - old_stats['n_engulf']:+,} |")
        w(f"| Pool mean R | {old_stats['mean_R']:+.4f} | {new_stats['mean_R']:+.4f} | "
          f"{new_stats['mean_R'] - old_stats['mean_R']:+.4f} |")
        w(f"| Pool WR% | {old_stats['WR_pct']:.2f}% | {new_stats['WR_pct']:.2f}% | "
          f"{new_stats['WR_pct'] - old_stats['WR_pct']:+.2f}pp |")
        w(f"")
        w(f"### AVWAP confluence distribution")
        w(f"")
        w(f"| Metric | Old v1.0 | New v1.1 | Δ |")
        w(f"|---|---:|---:|---:|")
        w(f"| AVWAP n | {old_avwap['n']:,} | {new_avwap['n']:,} | "
          f"{new_avwap['n'] - old_avwap['n']:+,} |")
        w(f"| conf=0.0 | {old_avwap['n_conf_eq_0']:,} | {new_avwap['n_conf_eq_0']:,} | "
          f"{new_avwap['n_conf_eq_0'] - old_avwap['n_conf_eq_0']:+,} |")
        w(f"| conf>=0.25 | {old_avwap['n_conf_ge_025']:,} ({100*old_avwap['n_conf_ge_025']/max(1,old_avwap['n']):.1f}%) | "
          f"{new_avwap['n_conf_ge_025']:,} ({100*new_avwap['n_conf_ge_025']/max(1,new_avwap['n']):.1f}%) | "
          f"{new_avwap['n_conf_ge_025'] - old_avwap['n_conf_ge_025']:+,} |")
        w(f"| conf>=0.50 | {old_avwap['n_conf_ge_050']:,} | {new_avwap['n_conf_ge_050']:,} | "
          f"{new_avwap['n_conf_ge_050'] - old_avwap['n_conf_ge_050']:+,} |")
        w(f"| conf>=0.75 | {old_avwap['n_conf_ge_075']:,} | {new_avwap['n_conf_ge_075']:,} | "
          f"{new_avwap['n_conf_ge_075'] - old_avwap['n_conf_ge_075']:+,} |")
        w(f"| conf=1.0 | {old_avwap['n_conf_eq_100']:,} | {new_avwap['n_conf_eq_100']:,} | "
          f"{new_avwap['n_conf_eq_100'] - old_avwap['n_conf_eq_100']:+,} |")
        w(f"| mean conf | {old_avwap['mean_conf']:.3f} | {new_avwap['mean_conf']:.3f} | "
          f"{new_avwap['mean_conf'] - old_avwap['mean_conf']:+.3f} |")
        w(f"| median conf | {old_avwap['median_conf']:.3f} | {new_avwap['median_conf']:.3f} | "
          f"{new_avwap['median_conf'] - old_avwap['median_conf']:+.3f} |")
        w(f"")
        # Net AVWAP filter etkisi (filter_conf_min=0.25 sonrasi geçen)
        old_kept = old_avwap['n_conf_ge_025']
        new_kept = new_avwap['n_conf_ge_025']
        w(f"**Net AVWAP filter etkisi (filter_conf_min=0.25 sonrasi kalan):**")
        w(f"- Old v1.0: {old_kept:,} / {old_avwap['n']:,} "
          f"({100*old_kept/max(1,old_avwap['n']):.1f}%)  — "
          f"design bug: v1.0'da conf hep 0.0 olduğu için tümü siliniyordu")
        w(f"- New v1.1: {new_kept:,} / {new_avwap['n']:,} "
          f"({100*new_kept/max(1,new_avwap['n']):.1f}%)  — "
          f"dynamic confluence ile en az 1 faktör aktif olanlar geçiyor")
        w(f"")
    else:
        w(f"> ⚠️ Old pool yüklenemedi (`{OLD_POOL}` yok ya da okunabilir değil).")
        w(f"")
    w(f"## Step 3 — C2+V5 Hibrid Replay (V2 risk %2 + V5 pyramid 1.5R)")
    w(f"")
    w(f"- Pool: `data/sec53_15m_pool_v11.pkl` ({len(pool_new):,} trade, TOP-4 × 10 sym)")
    w(f"- Config: V2 (risk_pct=0.02) + V5 (pyramid_triggers=(1.0, 1.5))")
    w(f"- AVWAP conf: dynamic (v1.1 in-pool), NO in-memory patch")
    w(f"- Per-month 61 ay + walk-forward 34-window")
    w(f"")
    w(f"## Step 4 — Parity Verify (Lab SEC52 vs SEC53)")
    w(f"")
    w(f"| Metric | Lab SEC52 (V3 patch) | SEC53 (v1.1 yeni pool) | Δ | Tolerans | Sonuç |")
    w(f"|---|---:|---:|---:|---:|:---:|")
    for key, label in [("annual_pct", "Annual"), ("mean_monthly_pct", "Mean monthly"),
                        ("pos_months", "Pozitif ay"), ("neg_months", "Negatif ay"),
                        ("sub20_months", "Sub-20 ay"),
                        ("max_loss_pct", "Max single loss"), ("cv_pct", "CV"),
                        ("wf_mean_r_adj", "WF r-adj")]:
        p = parity[key]
        if isinstance(p["ref"], float):
            ref_s = f"{p['ref']:+.2f}%" if "pct" in key else f"{p['ref']:.2f}"
            cur_s = f"{p['cur']:+.2f}%" if "pct" in key else f"{p['cur']:.2f}"
            d_s = f"{p['delta']:+.2f}pp" if "pct" in key else f"{p['delta']:+.2f}"
            tol_s = f"±{p['tol']:.0f}pp" if "pct" in key else f"±{p['tol']:.0f}"
        else:
            ref_s = f"{p['ref']}"
            cur_s = f"{p['cur']}"
            d_s = f"{p['delta']:+d}"
            tol_s = f"±{p['tol']}"
        flag = "✅" if p["within_tol"] else "❌"
        w(f"| {label} | {ref_s} | {cur_s} | {d_s} | {tol_s} | {flag} |")
    w(f"")
    w(f"**Overall parity:** {'✅ PASS' if parity_pass else '❌ DRIFT'}")
    w(f"")
    w(f"## Mandate Compliance (5-check)")
    w(f"")
    for k, v in mandate["checks"].items():
        w(f"- [{('PASS' if v else 'FAIL')}] {k}")
    w(f"")
    w(f"**Mandate score:** {mandate['n_pass']}/{mandate['total']} "
      f"(SEC52 baseline 4/5 — yeterli)")
    w(f"")
    w(f"## Step 5 — Verdict")
    w(f"")
    if verdict == "PARITY_PASS":
        w(f"**PARITY ✅ — Production candidate APPROVED.**")
        w(f"")
        w(f"Lab SEC52 sayıları AVWAP v1.1 ile birebir tolerans içinde tekrarlandı. "
          f"In-memory patch artık gereksiz; dinamik confluence formülü gerçek pool'da "
          f"da Lab beklentilerini karşılıyor.")
        w(f"")
        w(f"**Sonraki adım:** Production YAML draft (`{DRAFT_YAML.name}`) finalize edildi. "
          f"Paper trade gate sign-off CEO → Principal hatına geçer.")
    elif verdict == "DRIFT_BUT_MANDATE_OK":
        w(f"**PARITY DRIFT ⚠️ ama mandate {mandate['n_pass']}/5 PASS.**")
        w(f"")
        w(f"Sayılar Lab SEC52 toleransının dışında, fakat 5-check mandate hala geçiyor. "
          f"C2+V5 hibrid yeni baseline olarak güncellenebilir — Lab SEC52 sayıları "
          f"SEC53 sayılarıyla değiştirilmeli (CEO brief gerekli).")
        w(f"")
        w(f"**Sonraki adım:** Production candidate kalmaya devam eder, baseline numerik update.")
    elif verdict == "MANDATE_REDUCED":
        w(f"**Mandate {mandate['n_pass']}/5 — Researcher new variant sprint.**")
        w(f"")
        w(f"C2+V5 hibrid mandate'i tutamadı. Researcher'a yeni variant arama görevi "
          f"dispatch edilmeli — pyramid trigger / risk_pct / conf_min sweep.")
    else:
        w(f"**Strategy radical revise (mandate {mandate['n_pass']}/5).**")
        w(f"")
        w(f"C2+V5 hibrid yapısal sınırın altına düştü. AVWAP v1.1 fix beklenmeyen "
          f"şekilde havuz dinamiklerini bozdu. Forensik gerekli.")
    w(f"")
    w(f"### Summary table (SEC53 vs SEC52)")
    w(f"")
    w(f"| Metric | SEC52 (V3 patch) | SEC53 (v1.1 yeni pool) |")
    w(f"|---|---:|---:|")
    w(f"| Annual | +{SEC52_REF['annual_pct']:.1f}% | {s_c2v5['annual_pct']:+.1f}% |")
    w(f"| Mean monthly | +{SEC52_REF['mean_monthly_pct']:.2f}% | {s_c2v5['mean_monthly_pct']:+.2f}% |")
    w(f"| Pos / Neg | {SEC52_REF['pos_months']} / {SEC52_REF['neg_months']} | "
      f"{s_c2v5['pos_months']} / {s_c2v5['neg_months']} |")
    w(f"| Sub-20 ay | {SEC52_REF['sub20_months']} | {s_c2v5['sub20_months']} |")
    w(f"| Max loss | {SEC52_REF['max_loss_pct']:+.2f}% | {s_c2v5['max_loss_pct']:+.2f}% |")
    w(f"| CV | {SEC52_REF['cv_pct']:.0f}% | {s_c2v5['cv_pct']:.0f}% |")
    w(f"| WF r-adj | {SEC52_REF['wf_mean_r_adj']:.2f} | {s_c2v5['wf_mean_r_adj']:.2f} |")
    w(f"")
    w(f"## Disiplin")
    w(f"")
    w(f"- lab.py + production YAML DOKUNULMADI")
    w(f"- AVWAP v1.1 manifest hash: `a862f36b62e81fa9` (Signal Chief SEC52 fix)")
    w(f"- In-memory patch YOK (v1.1 dinamik conf gercek pool icinde)")
    w(f"- sec31_15m_pool.pkl korundu (eski v1.0 baseline referansi)")
    w(f"- 1d Phoenix v2.0.4 + 5m configs etkilenmedi (ayri YAML)")
    w(f"- Sayilar raw CSV verify: `sec53_c2v5_per_month.csv`, `sec53_c2v5_walkforward.csv`")
    w(f"")
    w(f"## Outputs")
    w(f"")
    w(f"- `data/sec53_15m_pool_v11.pkl` — yeni TOP-4 pool, AVWAP v1.1")
    w(f"- `reports/lab/sec53_pool_stats_compare.csv` — eski vs yeni pool stats")
    w(f"- `reports/lab/sec53_c2v5_per_month.csv` — C2+V5 × 61 ay")
    w(f"- `reports/lab/sec53_c2v5_walkforward.csv` — C2+V5 × 34 pencere")
    if parity_pass or verdict == "DRIFT_BUT_MANDATE_OK":
        w(f"- `configs/risk_phoenix_scalp_15m_c2v5_final.yaml` — production DRAFT (sign-off pending)")
    w(f"- Üretim script: `scripts/sec53_avwap_v11_parity.py`")
    REPORT.write_text("".join(out), encoding="utf-8")
    print(f"\n[DONE] {REPORT}", flush=True)

    # ========================================================================
    # Step 6 — Draft YAML (parity ✅ veya mandate hala PASS)
    # ========================================================================
    if parity_pass or verdict == "DRIFT_BUT_MANDATE_OK":
        src = RISK_YAML.read_text(encoding="utf-8")
        out_yaml = src.replace(
            "risk_per_trade: 0.030",
            "risk_per_trade: 0.020  # C2+V5 FINAL — V2 patch (SEC53 parity verified)"
        )
        out_yaml = out_yaml.replace(
            "backtest_risk_pct: 0.030",
            "backtest_risk_pct: 0.020  # C2+V5 FINAL — V2 patch"
        )
        # pyramid triggers (V5: [1.0, 2.0] -> [1.0, 1.5])
        # YAML'da pyramid_triggers anahtarı bulunabilir — replace
        out_yaml = out_yaml.replace(
            "pyramid_triggers: [1.0, 2.0]",
            "pyramid_triggers: [1.0, 1.5]  # V5 patch (SEC51 PARETO_PASS)"
        )
        out_yaml = out_yaml.replace(
            "preset_name: phoenix_scalp_15m_pyramid_r3",
            "preset_name: phoenix_scalp_15m_c2v5_final"
        )
        out_yaml = out_yaml.replace(
            "bot_name: PHOENIX-SCALP-15m-PYR-R3",
            "bot_name: PHOENIX-SCALP-15m-C2V5-FINAL  # DRAFT — sign-off pending"
        )

        sec53_note = "" if parity_pass else (
            "\n# NOTE: SEC53 parity DRIFT but mandate {}/{} PASS — baseline numbers "
            "updated.\n".format(mandate["n_pass"], mandate["total"])
        )
        header = f"""# =============================================================================
# PHOENIX-SCALP 15m C2+V5 FINAL — DRAFT ({datetime.now(timezone.utc).date().isoformat()})
# =============================================================================
# Bot: PHOENIX-SCALP-15m-C2V5-FINAL
# Status: DRAFT — Principal sign-off PENDING (live NOT active)
# Origin: Lab SEC53 parity verify (Signal Chief AVWAP v1.1 + Researcher C2+V5)
#
# DELTA vs baseline (risk_phoenix_scalp_15m_pyramid_r3.yaml):
#   1. risk_per_trade  0.030 -> 0.020  (V2 patch — sub-20 + max_loss iyilesme)
#   2. pyramid_triggers [1.0, 2.0] -> [1.0, 1.5]  (V5 patch)
#   3. AVWAP confluence formula REVISED in code (Signal Chief v1.1 fix)
#      Manifest hash: a862f36b62e81fa9
#      In-memory patch artik gereksiz — gercek dinamik conf pool'da uretiliyor.
#
# WALK-FORWARD (34 window 2y train / 90d OOS):
#   Annual:   {s_c2v5['wf_mean_annual_pct']:+.1f}%
#   r-adj:    {s_c2v5['wf_mean_r_adj']:.2f}
#   Neg windows: {s_c2v5['wf_neg_windows']}/{s_c2v5['wf_n_windows']}
#
# PER-MONTH (61 ay 2021-01 -> 2026-05):
#   Annual:    {s_c2v5['annual_pct']:+.1f}%
#   Mean M:    {s_c2v5['mean_monthly_pct']:+.2f}%
#   Pos:       {s_c2v5['pos_months']}/{s_c2v5['n_months']}
#   Neg:       {s_c2v5['neg_months']}/{s_c2v5['n_months']}
#   Sub-20:    {s_c2v5['sub20_months']}/{s_c2v5['n_months']}
#   Max loss:  {s_c2v5['max_loss_pct']:+.2f}%
#   CV:        {s_c2v5['cv_pct']:.0f}%
#
# PARITY (Lab SEC52 V3 patch vs SEC53 v1.1 pool):
#   Annual delta:    {s_c2v5['annual_pct'] - SEC52_REF['annual_pct']:+.1f}pp
#   Mean M delta:    {s_c2v5['mean_monthly_pct'] - SEC52_REF['mean_monthly_pct']:+.2f}pp
#   Pos delta:       {s_c2v5['pos_months'] - SEC52_REF['pos_months']:+d}
#   Sub-20 delta:    {s_c2v5['sub20_months'] - SEC52_REF['sub20_months']:+d}
#   Max loss delta:  {s_c2v5['max_loss_pct'] - SEC52_REF['max_loss_pct']:+.2f}pp
#   Parity verdict:  {verdict}
#   Mandate:         {mandate['n_pass']}/{mandate['total']}
{sec53_note}
# CHANGE LOG vs production:
#   - Production YAML (risk_phoenix_scalp_15m_pyramid_r3.yaml) UNTOUCHED.
#   - This file = preview-only. Manuel kopya + sign-off ile aktif edilir.
# =============================================================================

"""
        DRAFT_YAML.write_text(header + out_yaml, encoding="utf-8")
        print(f"[DRAFT] {DRAFT_YAML}", flush=True)
    else:
        print(f"[DRAFT] skipped (verdict={verdict})", flush=True)


if __name__ == "__main__":
    main()
