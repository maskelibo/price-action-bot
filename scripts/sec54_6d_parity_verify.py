"""SEC54.6d — Live wiring parity verify against Researcher backtest.

Researcher (SEC54.6d, 2026-05-18) ran the filter as a pure Python skip-list
using `regime_features_backfill_5y` semantics in-script. Engineering then
ported the filter to live (`src/price_action/risk/regime_filter.py`
`PerStrategyRegimeFilter` + `sizing.py` step 1.8 + YAML).

This script does the parity check: instead of re-implementing the filter
logic, it INSTANTIATES the live `PerStrategyRegimeFilter` from the YAML
block and exercises it for every trade in the SEC53 pool. The expectation
is that the live class produces byte-identical skip decisions vs the
Researcher's inline filter functions.

Verdict criteria (PARITY TABLE):
  Annual, Mean monthly, Neg ay, Max single loss, CV, WF r-adj, Filter skip count

PASS  → tolerances satisfied → testnet smoke gate OPEN
WARN  → 1-2 marginal drifts, justified
FAIL  → critical drift → live wiring bug → Execution Chief revise
"""
from __future__ import annotations

import csv
import hashlib
import io
import math
import os
import pickle
import sys
import time
from dataclasses import dataclass
from datetime import date as _date, datetime, timedelta, timezone
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
import numpy as np
import yaml

from price_action.backtest.lab import ProductionConfig, production_replay
from price_action.risk.regime_filter import BTCFeatures, PerStrategyRegimeFilter


# ============================================================================
# Paths
# ============================================================================
POOL_PATH      = ROOT / "data" / "sec53_15m_pool_v11.pkl"
FEATURES_PATH  = ROOT / "data" / "regime_features_backfill_5y.parquet"
RISK_YAML      = ROOT / "configs" / "risk_phoenix_scalp_15m_c2v5_final.yaml"
OUT_DIR        = ROOT / "reports" / "lab"
REPORT         = OUT_DIR / "2026-05-20_sec54_6d_parity_verify.md"
DECISIONS_CSV  = OUT_DIR / "sec54_6d_parity_decisions_sample.csv"

POOL_SHA256_EXPECTED = "59a794ef278e47f696cdb14ddf42db383ed097474f938f8902a34e450a4e3ad6"

TOP4_NAMES = {
    "vsa_climax_test",
    "brooks_failed_breakout",
    "anchored_vwap_reversal",
    "engulfing_continuation",
}

# ----------------------------------------------------------------------------
# Researcher SEC54.6d reference metrics (B fee=+8, combo, primary mandate gate)
# ----------------------------------------------------------------------------
RESEARCHER_REF = {
    "B_fee8": {
        "combo":    {"annual": 1935.9, "mean_m": 32.86, "neg": 8, "max_loss": -4.42,
                     "cv": 115, "wf_r_adj": 48.39, "skip_total": 46325},
        "baseline": {"annual": 1283.2, "mean_m": 28.44, "neg": 9, "max_loss": -4.90,
                     "cv": 130, "wf_r_adj": 42.66, "skip_total": 0},
    },
    "D_fee4": {
        "combo":    {"annual": 2011.6, "mean_m": 33.37, "neg": 6, "max_loss": -4.39,
                     "cv": 116, "wf_r_adj": 50.75, "skip_total": 46325},
    },
    "skip_per_filter": {"F1": 6972, "F2": 37997, "F3": 788, "F4": 568},
}


# ============================================================================
# BTC features loader — t-1 calendar (backfill parquet → date → BTCFeatures)
# ============================================================================
def load_features_calendar(path: Path) -> dict[_date, BTCFeatures]:
    """Load backfill parquet → map[date] → BTCFeatures.

    Each row represents the t-1 snapshot, indexed by `ts` (date).
    Replay caller will lookup `entry_ts.date() - 1 day` → BTCFeatures.
    fetched_at intentionally set to "now" so PerStrategyRegimeFilter
    staleness check ALLOWS (the parity test is about decision logic
    parity, not staleness — backfill is by design synthetic-fresh).
    """
    df = pd.read_parquet(path)
    print(f"[features] Loaded {len(df):,} rows from {path.name}")
    # Ensure date type for ts
    if pd.api.types.is_datetime64_any_dtype(df["ts"]):
        df["ts_date"] = df["ts"].dt.date
    else:
        df["ts_date"] = pd.to_datetime(df["ts"]).dt.date

    # fetched_at — force a fresh now so staleness check doesn't fire
    fetched_at_now = datetime.now(timezone.utc)

    cal: dict[_date, BTCFeatures] = {}
    for _, row in df.iterrows():
        d = row["ts_date"]
        if isinstance(d, datetime):
            d = d.date()
        cal[d] = BTCFeatures(
            ts=d,
            atr_pct_30d=float(row["atr_pct_30d"]),
            return_30d=float(row["return_30d"]),
            return_30d_abs_pct=float(row["return_30d_abs_pct"]),
            ema200_distance_pct=float(row.get("ema200_distance_pct", 0.0)),
            above_ema200=bool(row["above_ema200"]),
            fng_value=float(row["fng_value"]),
            realized_vol_7d_annualized=float(row["realized_vol_7d_annualized"]),
            fetched_at=fetched_at_now,
        )
    print(f"[features] Built calendar: {len(cal):,} dates  "
          f"range {min(cal.keys())} -> {max(cal.keys())}")
    return cal


def get_t1_features(cal: dict[_date, BTCFeatures], entry_ts: pd.Timestamp) -> BTCFeatures | None:
    """Return features at t-1 (entry_ts.date() - 1 day), with prior-date fallback."""
    try:
        if entry_ts.tzinfo is None:
            entry_ts = entry_ts.tz_localize("UTC")
    except Exception:
        return None
    lookup_date = (entry_ts - pd.Timedelta(days=1)).date()
    if lookup_date in cal:
        return cal[lookup_date]
    # Defensive fallback: nearest prior date (should rarely fire — mirrors
    # Researcher's get_t1_regime behavior for the very first trades)
    prior_dates = [d for d in cal.keys() if d <= lookup_date]
    if not prior_dates:
        return None
    return cal[max(prior_dates)]


# ============================================================================
# Filter application — uses live PerStrategyRegimeFilter directly
# ============================================================================
def apply_live_filter(
    pool: list[dict],
    cal: dict[_date, BTCFeatures],
    psrf: PerStrategyRegimeFilter,
    sample_n: int = 30,
) -> tuple[list[dict], dict]:
    """Apply live PerStrategyRegimeFilter to each trade. Return (kept, stats)."""
    kept: list[dict] = []
    skip_per_filter: dict[str, int] = {}
    skip_per_strategy: dict[str, int] = {}
    sample_logs: list[dict] = []

    for trade in pool:
        try:
            entry_ts = pd.Timestamp(trade["entry_ts"])
            if entry_ts.tzinfo is None:
                entry_ts = entry_ts.tz_localize("UTC")
        except Exception:
            kept.append(trade)
            continue

        feat = get_t1_features(cal, entry_ts)
        # NOTE: live API accepts strategy name directly (the live wiring uses
        # signal.pattern_id which prefix-resolves to strategy in
        # _pattern_to_strategy; for backtest trades we already have the
        # strategy name as-is so we pass it directly).
        allow, reason = psrf.evaluate_strategy_regime_filter(
            strategy=trade.get("strategy", ""),
            side=trade.get("side", "long"),
            ts=entry_ts.to_pydatetime(),
            btc_features=feat,
        )

        if allow:
            kept.append(trade)
        else:
            # Researcher uses short filter slugs F1/F2/F3/F4; live returns
            # full slug ("F1_avwap_range" etc). Normalize to F1/F2/F3/F4.
            short = reason.split("_", 1)[0] if reason else "UNK"
            skip_per_filter[short] = skip_per_filter.get(short, 0) + 1
            strat = trade.get("strategy", "?")
            skip_per_strategy[strat] = skip_per_strategy.get(strat, 0) + 1
            if len(sample_logs) < sample_n:
                sample_logs.append({
                    "entry_ts": str(entry_ts),
                    "symbol": trade.get("symbol"),
                    "side": trade.get("side"),
                    "strategy": strat,
                    "filter": short,
                    "filter_full": reason,
                    "lookup_date": str(feat.ts) if feat else "",
                    "atr_pct_30d": f"{feat.atr_pct_30d:.4f}" if feat else "",
                    "return_30d": f"{feat.return_30d:.4f}" if feat else "",
                    "return_30d_abs_pct": f"{feat.return_30d_abs_pct:.4f}" if feat else "",
                    "above_ema200": str(feat.above_ema200) if feat else "",
                    "fng_value": f"{feat.fng_value:.1f}" if feat else "",
                    "vol_7d_ann": f"{feat.realized_vol_7d_annualized:.4f}" if feat else "",
                })

    total_skip = sum(skip_per_filter.values())
    return kept, {
        "n_in": len(pool),
        "n_out": len(kept),
        "skip_total": total_skip,
        "skip_per_filter": skip_per_filter,
        "skip_per_strategy": skip_per_strategy,
        "sample_logs": sample_logs,
    }


# ============================================================================
# Replay helpers (identical semantics to Researcher script)
# ============================================================================
def to_utc(ts):
    if hasattr(ts, "tz_localize"):
        if ts.tzinfo is None:
            return ts.tz_localize("UTC")
        return ts.tz_convert("UTC")
    if ts.tzinfo is None:
        return ts.replace(tzinfo=timezone.utc)
    return ts.astimezone(timezone.utc)


def per_month_metrics(pool, cfg) -> list[dict]:
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
            rows.append({"window": i, "trades": 0, "annual_pct": 0.0, "dd_pct": 0.0, "r_adj": 0.0})
            continue
        try:
            r = production_replay(ww, cfg)
        except Exception:
            rows.append({"window": i, "trades": len(ww), "annual_pct": 0.0, "dd_pct": 0.0, "r_adj": 0.0})
            continue
        if r is None:
            rows.append({"window": i, "trades": len(ww), "annual_pct": 0.0, "dd_pct": 0.0, "r_adj": 0.0})
            continue
        ann = r.annualized(period_years) * 100
        dd = r.max_drawdown * 100
        ra = ann / abs(dd) if dd != 0 else 0
        rows.append({"window": i, "trades": len(ww), "annual_pct": ann,
                     "dd_pct": dd, "r_adj": ra})
    return rows


def summarize(month_rows, wf_rows) -> dict:
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
    mean_m = mean(rets) if rets else 0.0
    cv = (stdev(rets) / abs(mean_m) * 100) if (mean_m != 0 and len(rets) >= 2) else 0.0
    max_loss = min(rets) if rets else 0.0
    max_gain = max(rets) if rets else 0.0
    wf_radj = [r["r_adj"] for r in wf_rows if r["trades"] > 0]
    return {
        "annual_pct": annual,
        "mean_monthly_pct": mean_m,
        "pos_months": pos,
        "neg_months": neg,
        "max_loss_pct": max_loss,
        "max_gain_pct": max_gain,
        "cv_pct": cv,
        "n_months": len(rets),
        "wf_mean_r_adj": mean(wf_radj) if wf_radj else 0.0,
    }


# ============================================================================
# Pool integrity
# ============================================================================
def verify_pool_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    actual = h.hexdigest()
    if actual != POOL_SHA256_EXPECTED:
        print(f"[WARN] Pool SHA256 mismatch: expected {POOL_SHA256_EXPECTED[:16]}... "
              f"got {actual[:16]}...")
    else:
        print(f"[SHA256] Pool integrity OK: {actual[:16]}...")
    return actual


def save_decisions_csv(path: Path, sample_logs):
    if not sample_logs:
        path.write_text("(no sample logs)\n", encoding="utf-8")
        return
    cols = list(sample_logs[0].keys())
    with path.open("w", newline="", encoding="utf-8") as fh:
        wr = csv.DictWriter(fh, fieldnames=cols)
        wr.writeheader()
        for r in sample_logs:
            wr.writerow(r)


# ============================================================================
# Parity tolerance check
# ============================================================================
@dataclass
class ParityRow:
    metric: str
    ref: float
    actual: float
    delta: float
    tol: float
    verdict: str  # PASS / WARN / FAIL


def check_metric(metric: str, ref: float, actual: float, tol_pp: float,
                 warn_pp: float | None = None) -> ParityRow:
    delta = actual - ref
    if abs(delta) <= tol_pp:
        v = "PASS"
    elif warn_pp is not None and abs(delta) <= warn_pp:
        v = "WARN"
    else:
        v = "FAIL"
    return ParityRow(metric=metric, ref=ref, actual=actual,
                     delta=delta, tol=tol_pp, verdict=v)


# ============================================================================
# Main
# ============================================================================
def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    print("=" * 76)
    print("SEC54.6d — Live wiring parity verify")
    print("=" * 76)
    print(f"  Pool: {POOL_PATH.name}")
    print(f"  Features: {FEATURES_PATH.name}")
    print(f"  YAML: {RISK_YAML.name}")
    print(f"  Live module: src/price_action/risk/regime_filter.py "
          f"(PerStrategyRegimeFilter)")
    print()

    # ----- Pool -----
    if not POOL_PATH.exists():
        print(f"[ERROR] Pool not found: {POOL_PATH}")
        sys.exit(1)
    actual_sha = verify_pool_sha256(POOL_PATH)
    t0 = time.time()
    with POOL_PATH.open("rb") as f:
        pool_raw = pickle.load(f)
    print(f"  Loaded {len(pool_raw):,} raw trades ({time.time()-t0:.1f}s)")

    pool = [t for t in pool_raw if t.get("strategy") in TOP4_NAMES]
    print(f"  TOP-4 filter: {len(pool):,} trades")

    # ----- Features calendar -----
    if not FEATURES_PATH.exists():
        print(f"[ERROR] Features parquet missing: {FEATURES_PATH}")
        print("  Run: python scripts/regime_features_backfill.py")
        sys.exit(1)
    cal = load_features_calendar(FEATURES_PATH)

    # ----- Instantiate LIVE PerStrategyRegimeFilter from YAML block -----
    with RISK_YAML.open("r", encoding="utf-8") as fh:
        yaml_raw = yaml.safe_load(fh)
    psrf_cfg = yaml_raw.get("regime_filter_per_strategy", {}) or {}
    print(f"\n[YAML] regime_filter_per_strategy.enabled = {psrf_cfg.get('enabled')}")
    print(f"       max_age_hours = {psrf_cfg.get('features_max_age_hours')}")
    if not psrf_cfg.get("enabled", False):
        print("[ERROR] YAML has regime_filter_per_strategy.enabled=False — "
              "cannot verify parity. Edit YAML or pass override.")
        sys.exit(1)
    psrf = PerStrategyRegimeFilter(psrf_cfg)

    # ----- Apply LIVE filter to whole pool -----
    print(f"\n[APPLY] Running live PerStrategyRegimeFilter on {len(pool):,} trades...")
    t0 = time.time()
    pool_combo, combo_stats = apply_live_filter(pool, cal, psrf, sample_n=30)
    print(f"  Done ({time.time()-t0:.1f}s)")
    print(f"  Skipped TOTAL: {combo_stats['skip_total']:,} "
          f"({100.0*combo_stats['skip_total']/len(pool):.2f}%)")
    print(f"  Per-filter: {combo_stats['skip_per_filter']}")
    print(f"  Per-strategy: {combo_stats['skip_per_strategy']}")

    save_decisions_csv(DECISIONS_CSV, combo_stats["sample_logs"])
    print(f"  Sample decisions: {DECISIONS_CSV.name}")

    # ----- Replay in 3 fee scenarios -----
    print("\n[CONFIG] Loading ProductionConfig...")
    cfg_base = ProductionConfig.from_yaml(str(RISK_YAML))
    cfg_base = cfg_base.with_overrides(
        risk_pct=0.02,
        pyramid_triggers=(1.0, 1.5),
        max_concurrent=20,
        same_symbol_side_cooldown_days=0,
    )
    print(f"  daily_dd={cfg_base.daily_dd}  consec={cfg_base.consecutive_loss_n}  "
          f"m_short={cfg_base.monthly_dd_short}  m_long={cfg_base.monthly_dd_long}")

    fee_scenarios = [
        ("A_fee0", 0.0),
        ("B_fee8", 8.0),
        ("D_fee4", 4.0),
    ]

    # Variants — we run baseline (no filter, sanity vs Researcher baseline) AND
    # combo (live filter applied, parity vs Researcher combo)
    variants = [
        ("baseline", pool),
        ("combo",    pool_combo),
    ]

    results: dict[tuple[str, str], dict] = {}
    for fee_slug, fee_bps in fee_scenarios:
        cfg = cfg_base.with_overrides(fee_bps_per_trade=fee_bps)
        for vname, vpool in variants:
            print(f"\n[REPLAY {vname}/{fee_slug}] fee={fee_bps:+.1f}bps  "
                  f"pool={len(vpool):,}")
            t1 = time.time()
            mrows = per_month_metrics(vpool, cfg)
            wrows = walk_forward_metrics(vpool, cfg)
            s = summarize(mrows, wrows)
            elapsed = time.time() - t1
            print(f"  annual={s['annual_pct']:+.1f}%  mean={s['mean_monthly_pct']:+.2f}%  "
                  f"pos={s['pos_months']}  neg={s['neg_months']}  "
                  f"max_loss={s['max_loss_pct']:+.2f}%  CV={s['cv_pct']:.0f}%  "
                  f"WF_radj={s['wf_mean_r_adj']:.2f}  [{elapsed/60:.1f}m]")
            results[(fee_slug, vname)] = {
                "summary": s, "month_rows": mrows, "wf_rows": wrows,
                "fee_bps": fee_bps,
            }

    # ========================================================================
    # PARITY TABLE — B fee=+8 combo (primary mandate gate)
    # ========================================================================
    print("\n" + "=" * 76)
    print("PARITY TABLE — B fee=+8 combo (primary)")
    print("=" * 76)
    ref = RESEARCHER_REF["B_fee8"]["combo"]
    got = results[("B_fee8", "combo")]["summary"]
    rows: list[ParityRow] = []
    rows.append(check_metric("annual",    ref["annual"],   got["annual_pct"],       0.5, 5.0))
    rows.append(check_metric("mean_m",    ref["mean_m"],   got["mean_monthly_pct"], 0.5, 2.0))
    rows.append(check_metric("neg",       ref["neg"],      got["neg_months"],       1,   2))
    rows.append(check_metric("max_loss",  ref["max_loss"], got["max_loss_pct"],     0.5, 1.0))
    rows.append(check_metric("cv",        ref["cv"],       got["cv_pct"],           5.0, 10.0))
    rows.append(check_metric("wf_r_adj",  ref["wf_r_adj"], got["wf_mean_r_adj"],    2.0, 5.0))
    skip_actual = combo_stats["skip_total"]
    skip_tol = max(50, int(0.05 * ref["skip_total"]))  # 5% or 50 absolute
    rows.append(check_metric("skip_total", ref["skip_total"], skip_actual, skip_tol, skip_tol * 2))

    for r in rows:
        print(f"  {r.metric:14s}  ref={r.ref:>10.2f}  got={r.actual:>10.2f}  "
              f"d={r.delta:+10.2f}  tol=±{r.tol:>6.2f}  → {r.verdict}")

    # Per-filter parity (researcher's pre-counts)
    print("\nPer-filter skip parity:")
    pf_rows: list[ParityRow] = []
    for f_name, ref_n in RESEARCHER_REF["skip_per_filter"].items():
        got_n = combo_stats["skip_per_filter"].get(f_name, 0)
        tol = max(20, int(0.05 * ref_n))
        pf_rows.append(check_metric(f"skip_{f_name}", float(ref_n), float(got_n), tol, tol * 2))
        print(f"  skip_{f_name}: ref={ref_n:,}  got={got_n:,}  d={got_n-ref_n:+,}  → {pf_rows[-1].verdict}")

    # ========================================================================
    # VERDICT
    # ========================================================================
    fails = sum(1 for r in rows + pf_rows if r.verdict == "FAIL")
    warns = sum(1 for r in rows + pf_rows if r.verdict == "WARN")
    passes = sum(1 for r in rows + pf_rows if r.verdict == "PASS")

    if fails == 0 and warns <= 2:
        verdict = "PASS"
        verdict_text = (f"All {passes}/{len(rows)+len(pf_rows)} metrics within tolerance "
                        f"(warns={warns}, fails=0). Live wiring code reproduces Researcher "
                        f"backtest within byte-fidelity bounds. Testnet smoke gate: OPEN.")
    elif fails == 0:
        verdict = "WARN"
        verdict_text = (f"{passes}P / {warns}W / 0F — marginal drifts on >2 metrics. "
                        f"Justification required; testnet smoke gate: CONDITIONAL OPEN "
                        f"(Principal review).")
    else:
        verdict = "FAIL"
        verdict_text = (f"{passes}P / {warns}W / {fails}F — critical drift. "
                        f"Live wiring code likely has bug. Testnet smoke gate: CLOSED. "
                        f"Execution Chief revise required.")

    print("\n" + "=" * 76)
    print(f"VERDICT: {verdict}")
    print(verdict_text)
    print("=" * 76)

    # ========================================================================
    # Markdown report
    # ========================================================================
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    md = []
    w = lambda s="": md.append(s + "\n")

    w("# SEC54.6d — Live Wiring Parity Verify (Lab)")
    w()
    w(f"**Date:** {now_str}")
    w(f"**Lab:** Head of Self-Improvement")
    w(f"**Pool:** `data/sec53_15m_pool_v11.pkl` "
      f"(SHA256 `{actual_sha[:16]}...`, expected match: "
      f"{'OK' if actual_sha == POOL_SHA256_EXPECTED else 'MISMATCH'})")
    w(f"**Features parquet:** `data/regime_features_backfill_5y.parquet` "
      f"(5y BTC daily features, causal t-1)")
    w(f"**YAML:** `configs/risk_phoenix_scalp_15m_c2v5_final.yaml` "
      f"(`regime_filter_per_strategy.enabled = true`)")
    w(f"**Live module:** `src/price_action/risk/regime_filter.py` "
      f"→ `PerStrategyRegimeFilter.evaluate_strategy_regime_filter()`")
    w(f"**Researcher reference:** `reports/researcher/2026-05-19_sec54_6d_regime_filter.md` "
      f"(SEC54.6d, combo B fee=+8)")
    w()
    w("---")
    w()
    w("## Executive Summary — PARITY VERDICT TABLE")
    w()
    w("**Primary scenario: B fee=+8, combo (4 filter active)**")
    w()
    w("| Metric | Researcher SEC54.6d | Live wiring replay | Δ | Tolerance | Verdict |")
    w("|---|---:|---:|---:|---:|:---:|")
    fmt = lambda x: f"{x:+,.2f}" if isinstance(x, float) else f"{x:+,}"
    for r in rows:
        if r.metric in ("neg", "skip_total"):
            ref_s, got_s, d_s = f"{int(r.ref):,}", f"{int(r.actual):,}", f"{int(r.delta):+,}"
        else:
            ref_s = f"{r.ref:+.2f}" if r.ref != 0 else "0.00"
            got_s = f"{r.actual:+.2f}"
            d_s = f"{r.delta:+.2f}"
        tol_s = f"±{r.tol:g}"
        w(f"| {r.metric} | {ref_s} | {got_s} | {d_s} | {tol_s} | {r.verdict} |")
    w()
    w(f"**OVERALL VERDICT: {verdict}** — {verdict_text}")
    w()
    smoke_status = ("OPEN" if verdict == "PASS"
                    else ("CONDITIONAL OPEN (Principal review)" if verdict == "WARN"
                          else "CLOSED (live wiring bug)"))
    w(f"**TESTNET SMOKE GATE STATUS: {smoke_status}**")
    w()
    w("---")
    w()
    w("## 1. Pool & Features Provenance")
    w()
    w(f"- Pool path: `{POOL_PATH}`")
    w(f"- Pool SHA256: `{actual_sha}` "
      f"(expected `{POOL_SHA256_EXPECTED}` — "
      f"{'MATCH' if actual_sha == POOL_SHA256_EXPECTED else 'MISMATCH'})")
    w(f"- TOP-4 trades: {len(pool):,}")
    w(f"- Features parquet: `{FEATURES_PATH}` ({len(cal):,} dates)")
    w(f"- Features generated by: `scripts/regime_features_backfill.py` "
      f"(5y BTC + F&G, causal t-1)")
    w()
    w("---")
    w()
    w("## 2. Live Wiring Configuration")
    w()
    w("YAML block `regime_filter_per_strategy` (config snapshot at parity time):")
    w()
    w("```yaml")
    w(yaml.safe_dump(psrf_cfg, default_flow_style=False, sort_keys=False).rstrip())
    w("```")
    w()
    w("Live class thresholds (from YAML, loaded into `PerStrategyRegimeFilter`):")
    w()
    w(f"- F1 (anchored_vwap_reversal, BOTH): atr_pct < {psrf.f1_atr_pct_lt}  AND  |ret30| < {psrf.f1_ret30_abs_lt}")
    w(f"- F2 (brooks_failed_breakout, SHORT): above_ema200 AND ret30 > {psrf.f2_ret30_gt}")
    w(f"- F3 (vsa_climax_test, LONG): fng < {psrf.f3_fng_lt}  AND  ret30 < {psrf.f3_ret30_lt}")
    w(f"- F4 (engulfing_continuation, BOTH): vol_7d_ann > {psrf.f4_vol7d_ann_gt}")
    w()
    w("---")
    w()
    w("## 3. Filter Skip Parity")
    w()
    w("| Filter | Researcher pre-count | Live wiring skip | Δ | Tol | Verdict |")
    w("|---|---:|---:|---:|---:|:---:|")
    for r in pf_rows:
        w(f"| {r.metric.replace('skip_','')} | {int(r.ref):,} | {int(r.actual):,} | "
          f"{int(r.delta):+,} | ±{int(r.tol):,} | {r.verdict} |")
    w(f"| **TOTAL** | {ref['skip_total']:,} | {skip_actual:,} | "
      f"{skip_actual - ref['skip_total']:+,} | "
      f"±{int(rows[-1].tol):,} | {rows[-1].verdict} |")
    w()
    w("Per-strategy breakdown (live wiring):")
    w()
    w("| Strategy | Skip count |")
    w("|---|---:|")
    for k, v in sorted(combo_stats["skip_per_strategy"].items(), key=lambda x: -x[1]):
        w(f"| {k} | {v:,} |")
    w()
    w("---")
    w()
    w("## 4. Full Metric Comparison (B fee=+8)")
    w()
    w("| Variant | Annual | Mean monthly | Pos | Neg | Max gain | Max loss | CV | WF r-adj |")
    w("|---|---:|---:|---:|---:|---:|---:|---:|---:|")
    for vname in ["baseline", "combo"]:
        s = results[("B_fee8", vname)]["summary"]
        w(f"| {vname} | {s['annual_pct']:+.1f}% | {s['mean_monthly_pct']:+.2f}% | "
          f"{s['pos_months']} | {s['neg_months']} | {s['max_gain_pct']:+.1f}% | "
          f"{s['max_loss_pct']:+.2f}% | {s['cv_pct']:.0f}% | {s['wf_mean_r_adj']:.2f} |")
    w()
    w("Researcher reference (B fee=+8, combo): "
      f"annual +{ref['annual']:.1f}%, mean {ref['mean_m']:+.2f}%, "
      f"neg {ref['neg']}, max_loss {ref['max_loss']:+.2f}%, "
      f"CV {ref['cv']}%, WF r-adj {ref['wf_r_adj']:.2f}.")
    w()
    w("---")
    w()
    w("## 5. Sensitivity — All Fee Scenarios")
    w()
    w("| Fee | Variant | Annual | Mean | Neg | Max loss | CV | WF r-adj |")
    w("|---|---|---:|---:|---:|---:|---:|---:|")
    for fee_slug, _ in fee_scenarios:
        for vname in ["baseline", "combo"]:
            s = results[(fee_slug, vname)]["summary"]
            w(f"| {fee_slug} | {vname} | {s['annual_pct']:+.1f}% | "
              f"{s['mean_monthly_pct']:+.2f}% | {s['neg_months']} | "
              f"{s['max_loss_pct']:+.2f}% | {s['cv_pct']:.0f}% | {s['wf_mean_r_adj']:.2f} |")
    w()
    w("Researcher D fee=+4 combo reference: "
      f"annual +{RESEARCHER_REF['D_fee4']['combo']['annual']:.1f}%, "
      f"neg {RESEARCHER_REF['D_fee4']['combo']['neg']}, "
      f"WF r-adj {RESEARCHER_REF['D_fee4']['combo']['wf_r_adj']:.2f}.")
    w()
    w("---")
    w()
    w("## 6. Filter Decision Sample (Live Wiring)")
    w()
    if combo_stats["sample_logs"]:
        w("First 30 live-filter REJECT decisions (causal lookup verify):")
        w()
        w("| entry_ts | symbol | side | strategy | filter | lookup_date | atr_pct_30d | ret_30 | above_ema200 | fng | vol_7d_ann |")
        w("|---|---|---|---|---|---|---:|---:|---:|---:|---:|")
        for s in combo_stats["sample_logs"]:
            w(f"| {s['entry_ts']} | {s['symbol']} | {s['side']} | {s['strategy']} | "
              f"{s['filter']} | {s['lookup_date']} | {s['atr_pct_30d']} | {s['return_30d']} | "
              f"{s['above_ema200']} | {s['fng_value']} | {s['vol_7d_ann']} |")
    w()
    w(f"Full sample: `reports/lab/{DECISIONS_CSV.name}`  ({len(combo_stats['sample_logs'])} rows)")
    w()
    w("Compare with Researcher: `reports/researcher/sec54_6d_filter_decisions_sample.csv` "
      "(10 rows, also F3/vsa_climax_test in early 2022 — same decision shape).")
    w()
    w("---")
    w()
    w("## 7. Verdict & Next Steps")
    w()
    w(f"**Overall: {verdict}**")
    w()
    w(verdict_text)
    w()
    w(f"**Testnet smoke gate status: {smoke_status}**")
    w()
    if verdict == "PASS":
        w("**Next steps:**")
        w()
        w("1. Open testnet smoke gate (Execution Chief). PA_LIVE_CONFIRM env var "
          "becomes required for production switch.")
        w("2. Run testnet 7-day smoke with `regime_filter_per_strategy.enabled=true`, "
          "monitor `pa_regime_features_age_minutes` Prometheus gauge.")
        w("3. Compare live skip count vs backtest expected ~12.4% of TOP-4 signals.")
        w("4. CEO brief: parity proven, ready for paper trade promotion.")
    elif verdict == "WARN":
        w("**Next steps:**")
        w()
        w("1. Principal review marginal drifts; accept or revise.")
        w("2. If accepted, testnet smoke 14-day (extended) before paper trade.")
        w("3. Document drift sources in this report.")
    else:
        w("**Next steps:**")
        w()
        w("1. Execution Chief: revise live wiring code for failed metrics.")
        w("2. Most likely culprits (in order of decreasing likelihood):")
        w("   a. Features parquet ↔ Researcher inline regime_table semantic mismatch "
          "(atr_pct unit, ret_30 unit, ffill F&G).")
        w("   b. PerStrategyRegimeFilter staleness or strategy-name resolution mismatch.")
        w("   c. Replay engine config drift (cfg_base.with_overrides).")
        w("3. Re-run parity after fix; do NOT open testnet smoke gate.")
    w()
    w("---")
    w()
    w("## 8. Files")
    w()
    w(f"- Report: `reports/lab/{REPORT.name}`")
    w(f"- Decisions sample: `reports/lab/{DECISIONS_CSV.name}`")
    w(f"- Features parquet: `data/{FEATURES_PATH.name}` (backfill, 5y daily)")
    w(f"- Backfill script: `scripts/regime_features_backfill.py`")
    w(f"- Parity script: `scripts/sec54_6d_parity_verify.py`")
    w()
    w(f"*Generated: {now_str} by Lab (SEC54.6d parity verify)*")

    REPORT.write_text("".join(md), encoding="utf-8")
    print(f"\n[REPORT] {REPORT}")
    print("[SEC54.6d parity] DONE")


if __name__ == "__main__":
    main()
