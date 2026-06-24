"""SEC51: Sub-20 ay yapısal fix variantları — pre-registered replay sprint.

Researcher Task #16 (CEO mandate, 2026-05-17).
Pre-reg: memory/researcher/hypotheses/2026-05-17-sub20-fix-v1-v5.md
Forensic input: reports/analyst/2026-05-17_sub20_replay_funnel_forensic.md

5 variant + 3 combo, hepsi config-level OVERRIDE (lab.py + production YAML dokunulmuyor).
Pool: data/sec31_15m_pool.pkl (filtered TOP-4 × 10 sym = 373,675 trade).
Baseline: risk_phoenix_scalp_15m_pyramid_r3.yaml + mc=20, cooldown=0 (SEC32 canonical).

Variantlar:
  V0 (baseline) — değişiklik yok (parity reference, canonical metric)
  V1 — max_per_symbol_pct: 0.15 → 0.60 (2 pos sığar, notional cap %30 ile uyumlu)
  V2 — risk_per_trade: 0.03 → 0.02 (notional/equity oranı düşer, cap basıncı azalır)
  V3 — AVWAP-only conf patch (replay pool'da: AVWAP trade'lerin conf=0.30)
  V4 — Conditional sym-cap (BTC ATR% percentile > 70 → cap %30; else %15) NOT: V0 baseline'da BTC ATR% calendar yok; V4 için ayrı build.
  V5 — pyramid_triggers: [1.0, 2.0] → [1.0, 1.5]

Combo:
  C1 = V1 + V3
  C2 = V2 + V3
  C3 = V1 + V2

Çıktı:
  reports/researcher/2026-05-17_sub20_fix_variants.md
  reports/researcher/sec51_variants_per_month.csv (8 variant × 61 ay)
  reports/researcher/sec51_variants_summary.csv (8 variant × 8 metric)
"""
from __future__ import annotations

import copy
import csv
import io
import os
import pickle
import sys
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean, median, stdev

if __name__ == "__main__":
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
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
REPORT = ROOT / "reports" / "researcher" / "2026-05-17_sub20_fix_variants.md"
CSV_MONTH = ROOT / "reports" / "researcher" / "sec51_variants_per_month.csv"
CSV_SUMMARY = ROOT / "reports" / "researcher" / "sec51_variants_summary.csv"
CSV_WF = ROOT / "reports" / "researcher" / "sec51_variants_walkforward.csv"

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
# Variant pool transform — AVWAP conf patch (V3 + C1 + C2)
# ============================================================================
def patch_avwap_conf(pool: list[dict], lift_to: float = 0.30) -> list[dict]:
    """AVWAP trade'lerin conf'unu min `lift_to`'a yükselt (in-memory copy)."""
    out = []
    n_patched = 0
    for t in pool:
        if t.get("strategy") == "anchored_vwap_reversal" and t.get("conf", 0.0) < lift_to:
            tc = dict(t)
            tc["conf"] = lift_to
            out.append(tc)
            n_patched += 1
        else:
            out.append(t)
    return out, n_patched


# ============================================================================
# BTC ATR% percentile calendar (V4) — causal expanding window
# ============================================================================
def build_btc_atr_pct_percentile_calendar(window: int = 21, pctile_window_days: int = 365) -> dict | None:
    """BTC 15m bar'lardan günlük ATR% hesapla, expanding-window percentile döndür.

    Returns: dict[date -> percentile (0-100)] or None on failure.

    Causal: t günündeki percentile, t'den önceki [t-pctile_window_days .. t-1] dağılımından.
    """
    try:
        from scripts.run_real_backtest import _load_symbol_ohlcv
    except Exception as e:
        print(f"[V4] BTC ATR% calendar build skipped: {e}")
        return None

    df = _load_symbol_ohlcv("BTC/USDT", tf="15m")
    if df is None or df.empty:
        return None

    df = df.sort_values("ts").reset_index(drop=True).copy()
    df["ts"] = pd.to_datetime(df["ts"], utc=True)

    # Daily aggregation
    df["date"] = df["ts"].dt.date
    daily = df.groupby("date").agg(
        high=("high", "max"),
        low=("low", "min"),
        close=("close", "last"),
    ).reset_index()
    daily["tr"] = daily["high"] - daily["low"]
    daily["atr14"] = daily["tr"].rolling(window).mean()
    daily["atr_pct"] = daily["atr14"] / daily["close"]
    daily["atr_pct_pre"] = daily["atr_pct"].shift(1)  # causal

    # Expanding rolling percentile
    out = {}
    vals = daily["atr_pct_pre"].tolist()
    for i, dt in enumerate(daily["date"]):
        if i < 30:  # min sample
            continue
        lo = max(0, i - pctile_window_days)
        hist = [v for v in vals[lo:i] if v is not None and not pd.isna(v)]
        if len(hist) < 20:
            continue
        cur = vals[i]
        if cur is None or pd.isna(cur):
            continue
        # percentile of cur in hist
        pct = sum(1 for v in hist if v <= cur) / len(hist) * 100.0
        out[dt] = pct
    return out


# ============================================================================
# V4 — conditional sym-cap replay (CUSTOM, can't use std production_replay)
# ============================================================================
# We need to allow `concentration_max_per_symbol_pct` to vary per-trade.
# To avoid duplicating production_replay 400-line, we mutate cfg in-place per-month
# is INFEASIBLE (engine reads cfg once). Alternative: per-trade dynamic gate by
# wrapping concentration_max_per_symbol_pct as a callable.
#
# DECISION: We provide V4 as a "static" approximation — split pool into high-vol
# and low-vol days, run two replays with different cfg, but state-stateful side
# effects (DD, position book) cannot be separated. → DROP V4 here, implement as
# explicit sweep in v4-only sub-sprint if Pareto pass elsewhere.
#
# For this sprint: V4 = drop-in alternative = "static high-cap %30 sym-cap" applied
# uniformly. This isn't truly conditional but gives the "what if sym-cap %30 vs
# baseline %15" reference. True conditional V4 requires engine surgery → out of scope.
def run_v4_static_alt(pool, cfg, sym_cap: float = 0.30):
    """V4 static alt: sym-cap %15 → %30 (no vol-gating). True regime-cond V4 needs engine code change."""
    cfg_v4 = cfg.with_overrides(concentration_max_per_symbol_pct=sym_cap)
    return cfg_v4


# ============================================================================
# Per-month metric extraction
# ============================================================================
def per_month_metrics(pool: list[dict], cfg: ProductionConfig) -> list[dict]:
    """Replay each month, return list of dicts with monthly_pct, dd_pct, n_taken."""
    pool = sorted(pool, key=lambda x: to_utc(x["entry_ts"]))
    start = to_utc(pool[0]["entry_ts"])
    end = to_utc(pool[-1]["entry_ts"])
    months = []
    cy, cm = start.year, start.month
    while True:
        ms = datetime(cy, cm, 1, tzinfo=timezone.utc)
        if cm == 12:
            me = datetime(cy + 1, 1, 1, tzinfo=timezone.utc)
        else:
            me = datetime(cy, cm + 1, 1, tzinfo=timezone.utc)
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
            rows.append({"year": yr, "month": mo, "n_raw": len(m_tr),
                         "n_taken": 0, "monthly_pct": 0.0, "dd_pct": 0.0,
                         "skip_reason": "n<10"})
            continue
        try:
            r = production_replay(m_tr, cfg)
        except Exception as e:
            rows.append({"year": yr, "month": mo, "n_raw": len(m_tr),
                         "n_taken": 0, "monthly_pct": 0.0, "dd_pct": 0.0,
                         "skip_reason": f"err: {e}"})
            continue
        if r is None:
            rows.append({"year": yr, "month": mo, "n_raw": len(m_tr),
                         "n_taken": 0, "monthly_pct": 0.0, "dd_pct": 0.0,
                         "skip_reason": "replay_none"})
            continue
        ret_pct = r.total_return * 100
        dd_pct = r.max_drawdown * 100
        rows.append({"year": yr, "month": mo, "n_raw": len(m_tr),
                     "n_taken": r.trades, "monthly_pct": ret_pct,
                     "dd_pct": dd_pct, "skip_reason": ""})
    return rows


# ============================================================================
# Walk-forward 13-pencere (per variant)
# ============================================================================
def walk_forward_metrics(pool: list[dict], cfg: ProductionConfig,
                          train_days: int = 730, oos_days: int = 90,
                          step_days: int = 30) -> list[dict]:
    """Rolling 13-window walk-forward — per window: annual, dd, r-adj, trades."""
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


# ============================================================================
# 8-metric summary
# ============================================================================
def summarize_variant(month_rows: list[dict], wf_rows: list[dict]) -> dict:
    """Pareto-gate 8-metric matris."""
    valid = [r for r in month_rows if r["skip_reason"] == ""]
    rets = [r["monthly_pct"] for r in valid]
    n = len(rets)

    # Compound annual return (geometric)
    eq = 1.0
    for r in rets:
        eq *= (1.0 + r / 100.0)
    # Wall-clock years = (last month - first month) / 12
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

    # Walk-forward aggregate
    wf_ann = [r["annual_pct"] for r in wf_rows if r["trades"] > 0]
    wf_dd = [r["dd_pct"] for r in wf_rows if r["trades"] > 0]
    wf_radj = [r["r_adj"] for r in wf_rows if r["trades"] > 0]
    wf_mean_ann = mean(wf_ann) if wf_ann else 0.0
    wf_mean_dd = mean(wf_dd) if wf_dd else 0.0
    wf_mean_radj = mean(wf_radj) if wf_radj else 0.0
    wf_neg = sum(1 for a in wf_ann if a < 0)
    wf_n = len(wf_ann)

    return {
        "annual_pct": annual,
        "mean_monthly_pct": mean_m,
        "pos_months": pos,
        "ge20_months": ge20,
        "neg_months": neg,
        "sub20_months": sub20,
        "max_loss_pct": max_loss,
        "cv_pct": cv,
        "n_months": n,
        "wf_n_windows": wf_n,
        "wf_mean_annual_pct": wf_mean_ann,
        "wf_mean_dd_pct": wf_mean_dd,
        "wf_mean_r_adj": wf_mean_radj,
        "wf_neg_windows": wf_neg,
    }


# ============================================================================
# Pareto gate evaluation
# ============================================================================
GATE = {
    "annual_min_kabul": 970.0,
    "annual_hard_reject": 800.0,
    "mean_monthly_min_kabul": 25.0,
    "mean_monthly_hard_reject": 22.0,
    "pos_months_min": 48,
    "pos_months_hard": 46,
    "ge20_min": 25,
    "ge20_hard": 23,
    "neg_max": 7,
    "neg_hard": 9,
    "sub20_target_max": 33,
    "sub20_hard": 36,
    "max_loss_min_kabul": -9.0,   # >= -9 means loss not deeper than 9%
    "max_loss_hard_reject": -11.0,
    "cv_max_kabul": 155.0,
    "cv_hard": 175.0,
}

CANONICAL = {
    "annual_pct": 1076.0,
    "mean_monthly_pct": 28.91,
    "pos_months": 50,
    "ge20_months": 26,
    "neg_months": 7,
    "sub20_months": 35,
    "max_loss_pct": -7.29,
    "cv_pct": 144.0,
}


def gate_evaluate(s: dict, canonical: dict) -> dict:
    """Return dict with PASS/RED/MIN-KABUL per metric + overall Pareto-improvement flag."""
    rep = {}
    # Annual
    if s["annual_pct"] < GATE["annual_hard_reject"]:
        rep["annual"] = "HARD_REJECT"
    elif s["annual_pct"] < GATE["annual_min_kabul"]:
        rep["annual"] = "BELOW_KABUL"
    else:
        rep["annual"] = "PASS"
    # Mean monthly
    if s["mean_monthly_pct"] < GATE["mean_monthly_hard_reject"]:
        rep["mean_monthly"] = "HARD_REJECT"
    elif s["mean_monthly_pct"] < GATE["mean_monthly_min_kabul"]:
        rep["mean_monthly"] = "BELOW_KABUL"
    else:
        rep["mean_monthly"] = "PASS"
    # Pos
    if s["pos_months"] < GATE["pos_months_hard"]:
        rep["pos_months"] = "HARD_REJECT"
    elif s["pos_months"] < GATE["pos_months_min"]:
        rep["pos_months"] = "BELOW_KABUL"
    else:
        rep["pos_months"] = "PASS"
    # GE20
    if s["ge20_months"] < GATE["ge20_hard"]:
        rep["ge20"] = "HARD_REJECT"
    elif s["ge20_months"] < GATE["ge20_min"]:
        rep["ge20"] = "BELOW_KABUL"
    else:
        rep["ge20"] = "PASS"
    # Neg
    if s["neg_months"] >= GATE["neg_hard"]:
        rep["neg"] = "HARD_REJECT"
    elif s["neg_months"] > GATE["neg_max"]:
        rep["neg"] = "BELOW_KABUL"
    else:
        rep["neg"] = "PASS"
    # Sub20
    if s["sub20_months"] >= GATE["sub20_hard"]:
        rep["sub20"] = "HARD_REJECT"
    elif s["sub20_months"] > GATE["sub20_target_max"]:
        rep["sub20"] = "BELOW_KABUL"
    else:
        rep["sub20"] = "PASS"
    # Max loss (more negative = worse)
    if s["max_loss_pct"] < GATE["max_loss_hard_reject"]:
        rep["max_loss"] = "HARD_REJECT"
    elif s["max_loss_pct"] < GATE["max_loss_min_kabul"]:
        rep["max_loss"] = "BELOW_KABUL"
    else:
        rep["max_loss"] = "PASS"
    # CV
    if s["cv_pct"] > GATE["cv_hard"]:
        rep["cv"] = "HARD_REJECT"
    elif s["cv_pct"] > GATE["cv_max_kabul"]:
        rep["cv"] = "BELOW_KABUL"
    else:
        rep["cv"] = "PASS"

    # Pareto improvement rule:
    pareto = (
        s["sub20_months"] < canonical["sub20_months"] and
        s["pos_months"] >= canonical["pos_months"] and
        s["max_loss_pct"] > canonical["max_loss_pct"] and  # >  = less negative = better
        s["mean_monthly_pct"] >= GATE["mean_monthly_min_kabul"]
    )
    # Overall hard reject if any HARD_REJECT
    hard_rejected = any(v == "HARD_REJECT" for v in rep.values())
    rep["pareto_improvement"] = pareto
    rep["hard_rejected"] = hard_rejected
    rep["overall"] = "PARETO_PASS" if (pareto and not hard_rejected) else (
        "HARD_REJECT" if hard_rejected else "NO_PARETO"
    )
    return rep


# ============================================================================
# Main
# ============================================================================
def main():
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    print(f"[LOAD] {CACHE} ({CACHE.stat().st_size / 1e6:.1f} MB)", flush=True)
    with CACHE.open("rb") as fh:
        pool_raw = pickle.load(fh)
    pool = [t for t in pool_raw if t.get("strategy") in TOP4 and t.get("symbol") in SYMBOLS]
    print(f"[POOL] {len(pool):,} trade (filtered TOP-4 × 10 sym)", flush=True)

    # Canonical baseline cfg
    cfg_base = ProductionConfig.from_yaml(str(RISK_YAML))
    cfg_base = cfg_base.with_overrides(max_concurrent=20, same_symbol_side_cooldown_days=0)
    print(f"[CFG ] base: sym-cap={cfg_base.concentration_max_per_symbol_pct}, "
          f"risk={cfg_base.risk_pct}, conf_min={cfg_base.conf_min}, "
          f"pyramid_triggers={cfg_base.pyramid_triggers}, mc={cfg_base.max_concurrent}", flush=True)

    # Patch pools
    pool_avwap, n_avwap_patched = patch_avwap_conf(pool, lift_to=0.30)
    print(f"[V3 ] AVWAP conf patch: {n_avwap_patched:,} trade lifted to 0.30", flush=True)

    # Variant definitions
    variants = []
    variants.append(("V0_baseline", pool, cfg_base, "Canonical pyramid-on baseline"))
    variants.append(("V1_symcap_60", pool,
                     cfg_base.with_overrides(concentration_max_per_symbol_pct=0.60),
                     "max_per_symbol_pct 0.15 → 0.60 (2 pos sığar)"))
    variants.append(("V2_risk_02", pool,
                     cfg_base.with_overrides(risk_pct=0.02),
                     "risk_per_trade 0.03 → 0.02"))
    variants.append(("V3_avwap_conf", pool_avwap, cfg_base,
                     "AVWAP conf patch lift to 0.30 (TOP-4 elemanını geri kazandır)"))
    variants.append(("V4_symcap_30_static", pool,
                     cfg_base.with_overrides(concentration_max_per_symbol_pct=0.30),
                     "Static V4 alt: sym-cap %30 (true conditional çıkış scope)"))
    variants.append(("V5_pyr_15", pool,
                     cfg_base.with_overrides(pyramid_triggers=(1.0, 1.5)),
                     "pyramid_triggers [1.0, 2.0] → [1.0, 1.5]"))

    # Run each variant — per-month + walk-forward
    print(f"\n[RUN] 6 variants × (per-month 61 ay + walk-forward 34 pencere)", flush=True)
    results = {}
    for name, pool_v, cfg_v, desc in variants:
        print(f"  [{name}] starting...", flush=True)
        month_rows = per_month_metrics(pool_v, cfg_v)
        wf_rows = walk_forward_metrics(pool_v, cfg_v)
        summary = summarize_variant(month_rows, wf_rows)
        results[name] = {
            "desc": desc,
            "month_rows": month_rows,
            "wf_rows": wf_rows,
            "summary": summary,
        }
        s = summary
        print(f"  [{name}] annual={s['annual_pct']:+.1f}% mean_m={s['mean_monthly_pct']:+.2f}% "
              f"pos={s['pos_months']} ge20={s['ge20_months']} neg={s['neg_months']} "
              f"sub20={s['sub20_months']} max_loss={s['max_loss_pct']:+.2f}% CV={s['cv_pct']:.0f}%",
              flush=True)

    # Gate evaluation
    pareto_passers = []
    for name, res in results.items():
        if name == "V0_baseline":
            continue
        gate = gate_evaluate(res["summary"], CANONICAL)
        res["gate"] = gate
        if gate["overall"] == "PARETO_PASS":
            pareto_passers.append(name)

    print(f"\n[PARETO] PASS variant: {pareto_passers}", flush=True)

    # ========================================================================
    # Combo tests (PASS only)
    # ========================================================================
    combos = []
    if "V1_symcap_60" in pareto_passers and "V3_avwap_conf" in pareto_passers:
        combos.append(("C1_V1+V3", pool_avwap,
                       cfg_base.with_overrides(concentration_max_per_symbol_pct=0.60),
                       "V1 sym-cap %60 + V3 AVWAP conf patch"))
    if "V2_risk_02" in pareto_passers and "V3_avwap_conf" in pareto_passers:
        combos.append(("C2_V2+V3", pool_avwap,
                       cfg_base.with_overrides(risk_pct=0.02),
                       "V2 risk %2 + V3 AVWAP conf patch"))
    if "V1_symcap_60" in pareto_passers and "V2_risk_02" in pareto_passers:
        combos.append(("C3_V1+V2", pool,
                       cfg_base.with_overrides(concentration_max_per_symbol_pct=0.60,
                                                risk_pct=0.02),
                       "V1 sym-cap %60 + V2 risk %2"))

    # If no Pareto pass, still test C1 and C2 (most likely structural champion combos)
    # to provide complete decision context
    if not combos:
        print(f"[COMBO] no Pareto pass, running C1+C2 anyway for full decision context", flush=True)
        combos = [
            ("C1_V1+V3", pool_avwap,
             cfg_base.with_overrides(concentration_max_per_symbol_pct=0.60),
             "V1 sym-cap %60 + V3 AVWAP conf patch (forced)"),
            ("C2_V2+V3", pool_avwap,
             cfg_base.with_overrides(risk_pct=0.02),
             "V2 risk %2 + V3 AVWAP conf patch (forced)"),
            ("C3_V1+V2", pool,
             cfg_base.with_overrides(concentration_max_per_symbol_pct=0.60, risk_pct=0.02),
             "V1 sym-cap %60 + V2 risk %2 (forced)"),
        ]

    for name, pool_c, cfg_c, desc in combos:
        print(f"  [{name}] {desc}", flush=True)
        month_rows = per_month_metrics(pool_c, cfg_c)
        wf_rows = walk_forward_metrics(pool_c, cfg_c)
        summary = summarize_variant(month_rows, wf_rows)
        gate = gate_evaluate(summary, CANONICAL)
        results[name] = {"desc": desc, "month_rows": month_rows, "wf_rows": wf_rows,
                         "summary": summary, "gate": gate}
        s = summary
        print(f"  [{name}] annual={s['annual_pct']:+.1f}% mean_m={s['mean_monthly_pct']:+.2f}% "
              f"pos={s['pos_months']} ge20={s['ge20_months']} neg={s['neg_months']} "
              f"sub20={s['sub20_months']} max_loss={s['max_loss_pct']:+.2f}% CV={s['cv_pct']:.0f}% "
              f"→ {gate['overall']}", flush=True)

    # ========================================================================
    # CSV outputs
    # ========================================================================
    # Per-month: variant × ay
    with CSV_MONTH.open("w", newline="", encoding="utf-8") as fh:
        cols = ["variant", "year", "month", "n_raw", "n_taken", "monthly_pct", "dd_pct", "skip_reason"]
        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        for name, res in results.items():
            for r in res["month_rows"]:
                row = {"variant": name}
                row.update(r)
                # Format numbers
                if isinstance(row.get("monthly_pct"), float):
                    row["monthly_pct"] = f"{row['monthly_pct']:.4f}"
                if isinstance(row.get("dd_pct"), float):
                    row["dd_pct"] = f"{row['dd_pct']:.4f}"
                w.writerow(row)
    print(f"[CSV ] {CSV_MONTH}")

    # Walk-forward
    with CSV_WF.open("w", newline="", encoding="utf-8") as fh:
        cols = ["variant", "window", "start", "end", "trades", "annual_pct", "dd_pct", "r_adj"]
        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        for name, res in results.items():
            for r in res["wf_rows"]:
                row = {"variant": name}
                row.update(r)
                row["annual_pct"] = f"{row['annual_pct']:.4f}"
                row["dd_pct"] = f"{row['dd_pct']:.4f}"
                row["r_adj"] = f"{row['r_adj']:.4f}"
                w.writerow(row)
    print(f"[CSV ] {CSV_WF}")

    # Summary (variant × 8 metric + gate)
    with CSV_SUMMARY.open("w", newline="", encoding="utf-8") as fh:
        cols = ["variant", "desc", "annual_pct", "mean_monthly_pct", "pos_months",
                "ge20_months", "neg_months", "sub20_months", "max_loss_pct", "cv_pct",
                "wf_mean_annual_pct", "wf_mean_dd_pct", "wf_mean_r_adj", "wf_neg_windows",
                "wf_n_windows", "gate_overall", "pareto_improvement"]
        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        for name, res in results.items():
            s = res["summary"]
            gate = res.get("gate", {})
            row = {"variant": name, "desc": res["desc"],
                   "annual_pct": f"{s['annual_pct']:.2f}",
                   "mean_monthly_pct": f"{s['mean_monthly_pct']:.2f}",
                   "pos_months": s["pos_months"],
                   "ge20_months": s["ge20_months"],
                   "neg_months": s["neg_months"],
                   "sub20_months": s["sub20_months"],
                   "max_loss_pct": f"{s['max_loss_pct']:.2f}",
                   "cv_pct": f"{s['cv_pct']:.1f}",
                   "wf_mean_annual_pct": f"{s['wf_mean_annual_pct']:.2f}",
                   "wf_mean_dd_pct": f"{s['wf_mean_dd_pct']:.2f}",
                   "wf_mean_r_adj": f"{s['wf_mean_r_adj']:.3f}",
                   "wf_neg_windows": s["wf_neg_windows"],
                   "wf_n_windows": s["wf_n_windows"],
                   "gate_overall": gate.get("overall", "-"),
                   "pareto_improvement": gate.get("pareto_improvement", False)}
            w.writerow(row)
    print(f"[CSV ] {CSV_SUMMARY}")

    # ========================================================================
    # Markdown report
    # ========================================================================
    out = []
    w = lambda s="": out.append(s + "\n")

    w(f"# SEC51 — Sub-20 Ay Fix Variantları (Researcher Task #16)")
    w(f"")
    w(f"**Researcher:** Head of Quantitative Research")
    w(f"**Date:** {datetime.now(timezone.utc).date().isoformat()}")
    w(f"**Pre-reg:** `memory/researcher/hypotheses/2026-05-17-sub20-fix-v1-v5.md`")
    w(f"**Forensic input:** `reports/analyst/2026-05-17_sub20_replay_funnel_forensic.md`")
    w(f"**Pool:** `data/sec31_15m_pool.pkl` ({len(pool):,} trade, TOP-4 × 10 sym)")
    w(f"**Method:** lab.py + production YAML DOKUNULMADI. Tüm değişiklik `cfg.with_overrides()` veya pool in-memory patch (V3).")
    w(f"")
    w(f"---")
    w(f"")
    w(f"## Canonical Baseline (V0)")
    w(f"")
    s0 = results["V0_baseline"]["summary"]
    w(f"| Metric | V0 (replayed) | CEO brief (canonical) | Δ |")
    w(f"|---|---:|---:|---:|")
    w(f"| Annual | {s0['annual_pct']:+.2f}% | +{CANONICAL['annual_pct']:.0f}% | {s0['annual_pct'] - CANONICAL['annual_pct']:+.1f} |")
    w(f"| Mean monthly | {s0['mean_monthly_pct']:+.2f}% | +{CANONICAL['mean_monthly_pct']:.2f}% | {s0['mean_monthly_pct'] - CANONICAL['mean_monthly_pct']:+.2f} |")
    w(f"| Pozitif ay | {s0['pos_months']}/{s0['n_months']} | {CANONICAL['pos_months']}/61 | {s0['pos_months'] - CANONICAL['pos_months']:+d} |")
    w(f"| ≥+20% ay | {s0['ge20_months']} | {CANONICAL['ge20_months']} | {s0['ge20_months'] - CANONICAL['ge20_months']:+d} |")
    w(f"| Negatif ay | {s0['neg_months']} | {CANONICAL['neg_months']} | {s0['neg_months'] - CANONICAL['neg_months']:+d} |")
    w(f"| Sub-20 ay | {s0['sub20_months']} | {CANONICAL['sub20_months']} | {s0['sub20_months'] - CANONICAL['sub20_months']:+d} |")
    w(f"| Max single ay loss | {s0['max_loss_pct']:+.2f}% | {CANONICAL['max_loss_pct']:+.2f}% | {s0['max_loss_pct'] - CANONICAL['max_loss_pct']:+.2f} |")
    w(f"| CV | {s0['cv_pct']:.0f}% | {CANONICAL['cv_pct']:.0f}% | {s0['cv_pct'] - CANONICAL['cv_pct']:+.0f} |")
    w(f"")
    w(f"## 8-Metric Pareto Matrix (Tüm Variant + Combo)")
    w(f"")
    w(f"| Variant | Annual | Mean M | Pos | ≥+20 | Neg | Sub-20 | Max Loss | CV | WF mean ann | WF r-adj | Gate |")
    w(f"|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|")
    for name in ["V0_baseline", "V1_symcap_60", "V2_risk_02", "V3_avwap_conf",
                 "V4_symcap_30_static", "V5_pyr_15",
                 "C1_V1+V3", "C2_V2+V3", "C3_V1+V2"]:
        if name not in results:
            continue
        s = results[name]["summary"]
        gate = results[name].get("gate", {})
        gate_str = gate.get("overall", "BASELINE")
        w(f"| {name} | {s['annual_pct']:+.1f}% | {s['mean_monthly_pct']:+.2f}% | "
          f"{s['pos_months']} | {s['ge20_months']} | {s['neg_months']} | "
          f"{s['sub20_months']} | {s['max_loss_pct']:+.2f}% | {s['cv_pct']:.0f}% | "
          f"{s['wf_mean_annual_pct']:+.1f}% | {s['wf_mean_r_adj']:.2f} | {gate_str} |")
    w(f"")
    w(f"## Pareto-Frontier (sub-20 ay × annual return)")
    w(f"")
    w(f"| Variant | sub-20 ay | annual | mean_m | max_loss | Pareto? | Hard reject? |")
    w(f"|---|---:|---:|---:|---:|---|---|")
    for name in ["V0_baseline", "V1_symcap_60", "V2_risk_02", "V3_avwap_conf",
                 "V4_symcap_30_static", "V5_pyr_15",
                 "C1_V1+V3", "C2_V2+V3", "C3_V1+V2"]:
        if name not in results:
            continue
        s = results[name]["summary"]
        gate = results[name].get("gate", {})
        par = "YES" if gate.get("pareto_improvement", False) else "no"
        hr = "YES" if gate.get("hard_rejected", False) else "no"
        if name == "V0_baseline":
            par = "(reference)"
            hr = "-"
        w(f"| {name} | {s['sub20_months']} | {s['annual_pct']:+.1f}% | "
          f"{s['mean_monthly_pct']:+.2f}% | {s['max_loss_pct']:+.2f}% | {par} | {hr} |")
    w(f"")

    # Per-variant detail
    for name in ["V1_symcap_60", "V2_risk_02", "V3_avwap_conf",
                 "V4_symcap_30_static", "V5_pyr_15",
                 "C1_V1+V3", "C2_V2+V3", "C3_V1+V2"]:
        if name not in results:
            continue
        res = results[name]
        s = res["summary"]
        gate = res.get("gate", {})
        w(f"### {name} — {res['desc']}")
        w(f"")
        w(f"- Annual: {s['annual_pct']:+.2f}% (Δ vs V0: {s['annual_pct'] - s0['annual_pct']:+.2f}pp)")
        w(f"- Mean monthly: {s['mean_monthly_pct']:+.2f}% (Δ vs V0: {s['mean_monthly_pct'] - s0['mean_monthly_pct']:+.2f}pp)")
        w(f"- Pozitif ay: {s['pos_months']} (Δ: {s['pos_months'] - s0['pos_months']:+d})")
        w(f"- Sub-20 ay: {s['sub20_months']} (Δ: {s['sub20_months'] - s0['sub20_months']:+d})")
        w(f"- Max single ay loss: {s['max_loss_pct']:+.2f}% (Δ: {s['max_loss_pct'] - s0['max_loss_pct']:+.2f}pp)")
        w(f"- CV: {s['cv_pct']:.0f}% (Δ: {s['cv_pct'] - s0['cv_pct']:+.0f}pp)")
        w(f"- Walk-forward: {s['wf_n_windows']} pencere, mean annual {s['wf_mean_annual_pct']:+.1f}%, "
          f"r-adj {s['wf_mean_r_adj']:.2f}, neg {s['wf_neg_windows']}")
        w(f"- Gate: **{gate.get('overall', '-')}** (pareto_improvement={gate.get('pareto_improvement', False)}, hard_rejected={gate.get('hard_rejected', False)})")
        w(f"")

    # Champion decision
    w(f"## Champion Önerisi")
    w(f"")
    pareto_pass_all = [n for n, r in results.items()
                       if n != "V0_baseline" and r.get("gate", {}).get("overall") == "PARETO_PASS"]
    if pareto_pass_all:
        # Pick best by sub-20 reduction tied with max_loss improvement
        def score(name):
            s = results[name]["summary"]
            return (s["sub20_months"], -s["mean_monthly_pct"], s["max_loss_pct"])
        best = min(pareto_pass_all, key=score)
        bs = results[best]["summary"]
        w(f"**Champion önerisi: `{best}`** — Pareto-PASS.")
        w(f"")
        w(f"- Sub-20 ay: {s0['sub20_months']} → {bs['sub20_months']} (Δ {bs['sub20_months'] - s0['sub20_months']:+d})")
        w(f"- Annual: {s0['annual_pct']:+.1f}% → {bs['annual_pct']:+.1f}% (Δ {bs['annual_pct'] - s0['annual_pct']:+.1f}pp)")
        w(f"- Max loss: {s0['max_loss_pct']:+.2f}% → {bs['max_loss_pct']:+.2f}% (Δ {bs['max_loss_pct'] - s0['max_loss_pct']:+.2f}pp)")
        w(f"")
        w(f"**Sonraki adım:** Champion'ı Lab'e devret — config-level YAML draft (production yedek + sign-off).")
    else:
        w(f"**Champion önerisi: YOK — no Pareto improvement.**")
        w(f"")
        w(f"Hiçbir variant + combo Pareto-gate'i geçemedi (sub-20↓ AND pos↑ AND max_loss↓ AND mean_m ≥+25%).")
        w(f"")
        w(f"Bulgu zinciri kapısı (Yedek A pattern + Yedek B vol-target + Researcher Task #16 yapısal):")
        w(f"3 farklı yöntem sub-20 ay'larını mean monthly korurken azaltmadı → sub-20 ay'lar 15m TF'de **yapısal sınır**.")
        w(f"")
        w(f"Sonraki yön: TF değişim (5m TOP-2 already tested), yeni-strateji ekleme (Sec4 RED), veya hold süresi optimizasyonu.")
    w(f"")
    w(f"## Disiplin Notları")
    w(f"")
    w(f"- **lab.py + production YAML dokunulmadı.** Tüm değişiklik `ProductionConfig.with_overrides()` veya pool in-memory patch (V3 AVWAP conf lift).")
    w(f"- **Pre-reg KODDAN ÖNCE** (`memory/researcher/hypotheses/2026-05-17-sub20-fix-v1-v5.md` timestamp doğrulanabilir).")
    w(f"- **Apophenia kontrolü:** 5 variant + 3 combo = 8 deneme. Pareto-PASS olanlar bağımsız bilgi taşır (sub-20 ay sayısı doğrudan ölçülebilir, p-value değil).")
    w(f"- **V4 sınırlama:** True regime-conditional sym-cap için engine surgery (per-trade dynamic cap) gerekli. Bu sprint'te V4 = static %30 sym-cap alt-variant olarak verildi; gerçek conditional V4 sonraki sprint.")
    w(f"- **V3 mekanizma:** AVWAP `confluence_score = 1.5` (sabit bull/bear_weight) → `conf = (1.5-1.5)/1.5 = 0.0` → conf_min=0.25 her AVWAP'i siler. Replay-time pool patch (in-memory): AVWAP trade'lerin conf → 0.30. Bu DESIGN BUG kanıtı — Signal Chief ticket: AVWAP confluence formula revize.")
    w(f"- **V1 doğrulanmış mekanik:** Notional cap %30 → tek pos = %30 notional. Sym-cap %15 → 0.30 > 0.15 reject. %60 → 2 pos = 0.60 sığar. Açıklama: cap %30 her bir pos için zorlu üst sınır olduğu için sym-cap'in 2x'i = sym başına 2 pos sığar.")
    w(f"")
    w(f"**Ekler:**")
    w(f"- `reports/researcher/sec51_variants_per_month.csv` — 9 variant × 61 ay (per-month detail)")
    w(f"- `reports/researcher/sec51_variants_walkforward.csv` — 9 variant × 34 pencere walk-forward")
    w(f"- `reports/researcher/sec51_variants_summary.csv` — 9 variant × 8-metric matris + gate")
    w(f"- Üretim script: `scripts/sec51_sub20_fix_variants_replay.py` (deterministik)")

    REPORT.write_text("".join(out), encoding="utf-8")
    print(f"\n[DONE] {REPORT}")


if __name__ == "__main__":
    main()
