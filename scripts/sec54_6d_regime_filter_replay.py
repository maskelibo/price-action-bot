"""SEC54.6d — Per-Strategy Regime Conditional Filter Replay (Researcher Sprint, YOL-C).

Principal direktifi (2026-05-18 gece):
  - Neg ay azalt (10/61 → ≤9) PRIMARY
  - Max loss -%15 gevşek gate
  - Overnight çalış

4 Filter teklifi (HYP-2026-05-18 pre-reg, causal t-1 BTC daily lookup):
  F1: anchored_vwap_reversal → range rejim (BTC ATR%<3.0% & |ret30|<3%) → SKIP
  F2: brooks_failed_breakout SHORT → bull rejim (above_ema200 & ret30>+5%) → SKIP
  F3: vsa_climax_test LONG → bear rejim (F&G<15 & ret30<-10%) → SKIP
  F4: engulfing_continuation → high_vol rejim (vol_7d_ann>100%) → SKIP

Pool: data/sec53_15m_pool_v11.pkl (SHA256 59a794ef...) — TOP-4 × 10 sym
Config: configs/risk_phoenix_scalp_15m_c2v5_final.yaml (NEW YAML, C2+V5)
Replay knobs: SEC54.6 ile parity (risk_pct=0.02, pyramid (1.0,1.5), conc=20, cooldown=0)

Cikti:
  reports/researcher/2026-05-19_sec54_6d_regime_filter.md
  reports/researcher/sec54_6d_per_month_{combo,F1,F2,F3,F4}_{B_fee8,D_fee4}.csv
  reports/researcher/sec54_6d_walkforward_{combo}_{B_fee8,D_fee4}.csv
  reports/researcher/sec54_6d_filter_decisions_sample.csv
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
import numpy as np

from price_action.backtest.lab import ProductionConfig, production_replay


# ============================================================================
# Paths
# ============================================================================
POOL_PATH = ROOT / "data" / "sec53_15m_pool_v11.pkl"
OHLCV_PATH = ROOT / "data" / "v095_ohlcv_cache.pkl"
FNG_PATH = ROOT / "data" / "alt_data" / "fng_daily.csv"
RISK_YAML = ROOT / "configs" / "risk_phoenix_scalp_15m_c2v5_final.yaml"
OUT_DIR = ROOT / "reports" / "researcher"
REPORT = OUT_DIR / "2026-05-19_sec54_6d_regime_filter.md"

POOL_SHA256_EXPECTED = "59a794ef278e47f696cdb14ddf42db383ed097474f938f8902a34e450a4e3ad6"

TOP4_NAMES = {
    "vsa_climax_test",
    "brooks_failed_breakout",
    "anchored_vwap_reversal",
    "engulfing_continuation",
}

# SEC54.6 baseline (NEW YAML, fee scenarios) — reference for comparison
SEC54_6_BASELINE = {
    "B_fee8": {"annual": 1320.5, "mean_m": 28.85, "neg": 10, "max_loss": -13.82,
               "cv": 126, "wf_r_adj": 33.84, "pos": None, "ge20": None, "sub20": None},
    "D_fee4": {"annual": 1362.9, "mean_m": 29.19, "neg": 10, "max_loss": -13.68,
               "cv": 125, "wf_r_adj": 34.96, "pos": None, "ge20": None, "sub20": None},
}

# ============================================================================
# Regime feature engineering (CAUSAL t-1 BTC daily lookup)
# ============================================================================
def build_btc_regime_table(ohlcv_cache: dict, fng_df: pd.DataFrame) -> pd.DataFrame:
    """Build per-date causal BTC regime feature table.

    For trade with entry_date D, lookup row at date D-1 (t-1 close).
    Columns:
      atr_pct (already in cache, t-1 close-based ATR14 / close)
      ret_30 (30-day return, causal)
      above_ema200 (bool)
      fng_value (from F&G csv)
      vol_7d_ann (std(daily_return_7d) * sqrt(365))
    """
    btc = ohlcv_cache["BTC/USDT"].copy()
    btc["ts"] = pd.to_datetime(btc["ts"], utc=True)
    btc["date"] = btc["ts"].dt.normalize()
    btc = btc.sort_values("date").reset_index(drop=True)

    # vol_7d_ann (rolling std of daily returns × sqrt(365))
    btc["daily_ret"] = btc["close"].pct_change()
    btc["vol_7d"] = btc["daily_ret"].rolling(7).std()
    btc["vol_7d_ann"] = btc["vol_7d"] * math.sqrt(365) * 100  # in %

    # Causal alignment: shift features so that row's date represents t-1 close lookup target.
    # We do NOT shift here; instead caller does entry_date - 1 day to lookup row.
    # F&G merge on date
    fng = fng_df.copy()
    fng["date"] = pd.to_datetime(fng["date"], utc=True).dt.normalize()
    fng = fng[["date", "value"]].rename(columns={"value": "fng_value"})
    btc = btc.merge(fng, on="date", how="left")
    # Forward-fill F&G (occasionally missing days)
    btc["fng_value"] = btc["fng_value"].ffill()

    # Select features + date as index for fast lookup
    out = btc[["date", "atr_pct", "ret_30", "above_ema200", "fng_value",
               "vol_7d_ann"]].copy()
    out = out.set_index("date").sort_index()
    return out


def get_t1_regime(regime_tbl: pd.DataFrame, entry_ts: pd.Timestamp) -> dict | None:
    """Return regime features at t-1 (entry_ts.normalize() - 1 day).

    Returns None if lookup date not in table (early data before BTC history).
    """
    entry_date = entry_ts.normalize() - pd.Timedelta(days=1)
    if entry_date not in regime_tbl.index:
        # Try fallback: nearest prior date (defensive — should rarely fire)
        prior = regime_tbl.index[regime_tbl.index <= entry_date]
        if len(prior) == 0:
            return None
        entry_date = prior[-1]
    row = regime_tbl.loc[entry_date]
    return {
        "atr_pct": float(row["atr_pct"]) if pd.notna(row["atr_pct"]) else None,
        "ret_30": float(row["ret_30"]) if pd.notna(row["ret_30"]) else None,
        "above_ema200": bool(row["above_ema200"]) if pd.notna(row["above_ema200"]) else None,
        "fng_value": float(row["fng_value"]) if pd.notna(row["fng_value"]) else None,
        "vol_7d_ann": float(row["vol_7d_ann"]) if pd.notna(row["vol_7d_ann"]) else None,
        "lookup_date": entry_date,
    }


# ============================================================================
# Filter logic — per HYP-2026-05-18 pre-registered thresholds
# ============================================================================
def filter_F1_avwap_range(trade: dict, regime: dict) -> bool:
    """F1: anchored_vwap_reversal → range (ATR%<3.0% & |ret30|<3%) → SKIP (return True = SKIP).

    NOTE: cache stores atr_pct and ret_30 as ALREADY PERCENT VALUES (e.g. 3.96 = 3.96%),
    NOT fractions. So thresholds are compared raw.
    """
    if trade.get("strategy") != "anchored_vwap_reversal":
        return False
    if regime is None or regime["atr_pct"] is None or regime["ret_30"] is None:
        return False  # missing data → don't skip
    atr_pct = regime["atr_pct"]  # already in % units (cache convention)
    ret_30 = regime["ret_30"]    # already in % units
    if atr_pct < 3.0 and abs(ret_30) < 3.0:
        return True
    return False


def filter_F2_brooks_bull_short(trade: dict, regime: dict) -> bool:
    """F2: brooks_failed_breakout SHORT → bull (above_ema200 & ret30>+5%) → SKIP."""
    if trade.get("strategy") != "brooks_failed_breakout":
        return False
    if trade.get("side") != "short":
        return False
    if regime is None or regime["above_ema200"] is None or regime["ret_30"] is None:
        return False
    ret_30 = regime["ret_30"]  # already in % units
    if regime["above_ema200"] and ret_30 > 5.0:
        return True
    return False


def filter_F3_vsa_bear_long(trade: dict, regime: dict) -> bool:
    """F3: vsa_climax_test LONG → bear (F&G<15 & ret30<-10%) → SKIP."""
    if trade.get("strategy") != "vsa_climax_test":
        return False
    if trade.get("side") != "long":
        return False
    if regime is None or regime["fng_value"] is None or regime["ret_30"] is None:
        return False
    ret_30 = regime["ret_30"]  # already in % units
    if regime["fng_value"] < 15 and ret_30 < -10.0:
        return True
    return False


def filter_F4_engulfing_high_vol(trade: dict, regime: dict) -> bool:
    """F4: engulfing_continuation → high_vol (vol_7d_ann>100%) → SKIP."""
    if trade.get("strategy") != "engulfing_continuation":
        return False
    if regime is None or regime["vol_7d_ann"] is None:
        return False
    if regime["vol_7d_ann"] > 100.0:
        return True
    return False


FILTERS = {
    "F1": filter_F1_avwap_range,
    "F2": filter_F2_brooks_bull_short,
    "F3": filter_F3_vsa_bear_long,
    "F4": filter_F4_engulfing_high_vol,
}


def apply_filters(pool: list[dict], regime_tbl: pd.DataFrame,
                  active: set[str], log_sample: int = 5) -> tuple[list[dict], dict]:
    """Apply selected filters to pool. Return (filtered_pool, stats)."""
    out = []
    n_skipped = {k: 0 for k in FILTERS.keys()}
    n_skipped["TOTAL"] = 0
    sample_logs = []

    for trade in pool:
        try:
            entry_ts = pd.Timestamp(trade["entry_ts"])
            if entry_ts.tzinfo is None:
                entry_ts = entry_ts.tz_localize("UTC")
        except Exception:
            out.append(trade)
            continue
        regime = get_t1_regime(regime_tbl, entry_ts)

        skip = False
        skip_reason = None
        for fname in active:
            f = FILTERS[fname]
            if f(trade, regime):
                skip = True
                skip_reason = fname
                n_skipped[fname] += 1
                break  # first-match wins (but they're disjoint by strategy+side)

        if skip:
            n_skipped["TOTAL"] += 1
            if len(sample_logs) < log_sample:
                sample_logs.append({
                    "entry_ts": str(entry_ts),
                    "symbol": trade.get("symbol"),
                    "side": trade.get("side"),
                    "strategy": trade.get("strategy"),
                    "R_raw": trade.get("R"),
                    "filter": skip_reason,
                    "lookup_date": str(regime["lookup_date"]) if regime else None,
                    "atr_pct": regime["atr_pct"] if regime else None,
                    "ret_30": regime["ret_30"] if regime else None,
                    "above_ema200": regime["above_ema200"] if regime else None,
                    "fng_value": regime["fng_value"] if regime else None,
                    "vol_7d_ann": regime["vol_7d_ann"] if regime else None,
                })
        else:
            out.append(trade)
    return out, {"n_skipped_per_filter": n_skipped, "sample_logs": sample_logs,
                 "n_in": len(pool), "n_out": len(out)}


# ============================================================================
# Replay utilities (shared semantic with sec54_6_yaml_revise_replay.py)
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


def save_sample_decisions_csv(path: Path, sample_logs: list[dict]) -> None:
    if not sample_logs:
        path.write_text("(no sample logs)\n", encoding="utf-8")
        return
    cols = list(sample_logs[0].keys())
    with path.open("w", newline="", encoding="utf-8") as fh:
        wr = csv.DictWriter(fh, fieldnames=cols)
        wr.writeheader()
        for r in sample_logs:
            wr.writerow(r)


def mandate_check(s: dict) -> dict:
    """SEC54.6d gevşek mandate (Principal sign-off): max_loss -%15, neg≤9."""
    checks = {
        "annual_ge_1100": s["annual_pct"] >= 1100.0,
        "mean_monthly_ge_20": s["mean_monthly_pct"] >= 20.0,
        "neg_months_le_9": s["neg_months"] <= 9,
        "max_loss_ge_neg15": s["max_loss_pct"] >= -15.0,
        "wf_r_adj_ge_12": s["wf_mean_r_adj"] >= 12.0,
    }
    n_pass = sum(1 for v in checks.values() if v)
    return {"checks": checks, "n_pass": n_pass, "total": len(checks)}


# ============================================================================
# Main
# ============================================================================
def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    print("[SEC54.6d] Per-Strategy Regime Conditional Filter Replay", flush=True)
    print(f"  Pool: {POOL_PATH}", flush=True)
    print(f"  OHLCV: {OHLCV_PATH}", flush=True)
    print(f"  F&G: {FNG_PATH}", flush=True)
    print(f"  YAML: {RISK_YAML.name}", flush=True)
    print(f"  HYP: memory/researcher/hypotheses/2026-05-18-regime-conditional-filters.md",
          flush=True)

    # ========================================================================
    # Pool + OHLCV + F&G load
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

    print(f"\n[OHLCV] Loading {OHLCV_PATH.stat().st_size/1e6:.1f} MB...", flush=True)
    with OHLCV_PATH.open("rb") as f:
        ohlcv_cache = pickle.load(f)
    print(f"  BTC daily rows: {len(ohlcv_cache['BTC/USDT']):,}", flush=True)

    print(f"\n[F&G] Loading {FNG_PATH}...", flush=True)
    fng_df = pd.read_csv(FNG_PATH)
    print(f"  F&G rows: {len(fng_df):,}", flush=True)

    print(f"\n[REGIME] Building BTC regime table (causal t-1 lookup)...", flush=True)
    regime_tbl = build_btc_regime_table(ohlcv_cache, fng_df)
    print(f"  Regime table: {len(regime_tbl):,} rows, "
          f"range {regime_tbl.index.min().date()} -> {regime_tbl.index.max().date()}",
          flush=True)
    print(f"  Sample: atr_pct mean={regime_tbl['atr_pct'].mean()*100:.2f}%  "
          f"vol_7d_ann mean={regime_tbl['vol_7d_ann'].mean():.1f}%", flush=True)

    # ========================================================================
    # Filter pre-counts: how many trades would each filter skip alone
    # ========================================================================
    print(f"\n[FILTER PRE-COUNT] Apply each filter alone (dry-run)...", flush=True)
    pre_counts = {}
    for fname in FILTERS.keys():
        filtered, stats = apply_filters(pool, regime_tbl, active={fname}, log_sample=0)
        pre_counts[fname] = stats["n_skipped_per_filter"][fname]
        print(f"  {fname}: skip {pre_counts[fname]:,} / {len(pool):,} "
              f"({100.0*pre_counts[fname]/len(pool):.2f}%)", flush=True)

    # Combined (all 4)
    pool_combo, combo_stats = apply_filters(pool, regime_tbl, active=set(FILTERS.keys()),
                                              log_sample=10)
    print(f"  COMBO: skip {combo_stats['n_skipped_per_filter']['TOTAL']:,} / {len(pool):,} "
          f"({100.0*combo_stats['n_skipped_per_filter']['TOTAL']/len(pool):.2f}%)", flush=True)
    print(f"  per-filter (combo): {combo_stats['n_skipped_per_filter']}", flush=True)

    # Save sample filter decision log
    sample_csv = OUT_DIR / "sec54_6d_filter_decisions_sample.csv"
    save_sample_decisions_csv(sample_csv, combo_stats["sample_logs"])
    print(f"  Sample decisions: {sample_csv.name}", flush=True)

    # ========================================================================
    # Base config (NEW YAML, SEC54.6 parity)
    # ========================================================================
    print(f"\n[CONFIG] Loading {RISK_YAML.name}...", flush=True)
    cfg_base = ProductionConfig.from_yaml(str(RISK_YAML))
    cfg_base = cfg_base.with_overrides(
        risk_pct=0.02,
        pyramid_triggers=(1.0, 1.5),
        max_concurrent=20,
        same_symbol_side_cooldown_days=0,
    )
    print(f"  Breakers: daily={cfg_base.daily_dd}  consec={cfg_base.consecutive_loss_n}  "
          f"m_short={cfg_base.monthly_dd_short}  m_long={cfg_base.monthly_dd_long}", flush=True)

    # ========================================================================
    # Replay scenarios
    # ========================================================================
    # Primary scenario: B fee=+8 (Principal worst-case)
    # Plus D fee=+4 (realistic) for sensitivity
    fee_scenarios = [("B_fee8", 8.0), ("D_fee4", 4.0)]

    # Variants: combo (all 4), F1 only, F2 only, F3 only, F4 only, baseline (no filter)
    variants = [
        ("baseline", set()),  # no filter (verify against SEC54.6)
        ("F1", {"F1"}),
        ("F2", {"F2"}),
        ("F3", {"F3"}),
        ("F4", {"F4"}),
        ("combo", {"F1", "F2", "F3", "F4"}),
    ]

    results = {}
    for fee_slug, fee_bps in fee_scenarios:
        cfg = cfg_base.with_overrides(fee_bps_per_trade=fee_bps)
        for var_slug, active in variants:
            print(f"\n[REPLAY {var_slug} / {fee_slug}] fee={fee_bps:+.1f}bps  "
                  f"filters={sorted(active) if active else 'NONE'}", flush=True)
            if active:
                pool_var, var_stats = apply_filters(pool, regime_tbl, active=active,
                                                     log_sample=0)
                print(f"  Pool size: {len(pool):,} -> {len(pool_var):,} "
                      f"(skipped {len(pool)-len(pool_var):,})", flush=True)
            else:
                pool_var = pool
                var_stats = {"n_skipped_per_filter": {}, "n_in": len(pool),
                              "n_out": len(pool), "sample_logs": []}

            t1 = time.time()
            print(f"  per-month...", flush=True)
            month_rows = per_month_metrics(pool_var, cfg)
            print(f"  walk-forward...", flush=True)
            wf_rows = walk_forward_metrics(pool_var, cfg)
            s = summarize_variant(month_rows, wf_rows)
            elapsed = time.time() - t1
            mc = mandate_check(s)
            tag = "PASS" if mc["n_pass"] == 5 else ("WARN" if mc["n_pass"] == 4
                else ("MARGINAL" if mc["n_pass"] == 3 else "NO-GO"))
            print(f"  annual={s['annual_pct']:+.1f}%  mean={s['mean_monthly_pct']:+.2f}%  "
                  f"pos={s['pos_months']}  neg={s['neg_months']}  "
                  f"max_loss={s['max_loss_pct']:+.2f}%  CV={s['cv_pct']:.0f}%  "
                  f"WF_radj={s['wf_mean_r_adj']:.2f}  mandate={mc['n_pass']}/5 [{tag}]  "
                  f"[{elapsed/60:.1f}m]", flush=True)

            csv_m = OUT_DIR / f"sec54_6d_per_month_{var_slug}_{fee_slug}.csv"
            csv_w = OUT_DIR / f"sec54_6d_walkforward_{var_slug}_{fee_slug}.csv"
            save_month_csv(csv_m, month_rows)
            save_wf_csv(csv_w, wf_rows)

            results[(fee_slug, var_slug)] = {
                "summary": s, "mandate": mc, "var_stats": var_stats,
                "month_rows": month_rows, "wf_rows": wf_rows,
                "fee_bps": fee_bps, "csv_month": str(csv_m), "csv_wf": str(csv_w),
                "elapsed_s": elapsed,
            }

    # ========================================================================
    # Verify baseline parity with SEC54.6 (B fee=+8)
    # ========================================================================
    print(f"\n[PARITY] baseline (no filter) vs SEC54.6 B_fee8 reference...", flush=True)
    b_base = results[("B_fee8", "baseline")]["summary"]
    ref = SEC54_6_BASELINE["B_fee8"]
    annual_delta = abs(b_base["annual_pct"] - ref["annual"])
    print(f"  annual: got={b_base['annual_pct']:+.1f}%  ref=+{ref['annual']:.1f}%  "
          f"delta={annual_delta:+.1f}pp  tol=±5  "
          f"{'OK' if annual_delta<=5.0 else 'DRIFT'}", flush=True)
    print(f"  neg: got={b_base['neg_months']}  ref={ref['neg']}  "
          f"{'OK' if b_base['neg_months']==ref['neg'] else 'DRIFT'}", flush=True)

    # ========================================================================
    # Per-filter contribution analysis
    # ========================================================================
    print(f"\n[CONTRIBUTION] Per-filter neg-month reduction (B fee=+8)...", flush=True)
    b_base_neg = results[("B_fee8", "baseline")]["summary"]["neg_months"]
    for var_slug in ["F1", "F2", "F3", "F4", "combo"]:
        v = results[("B_fee8", var_slug)]["summary"]
        delta_neg = v["neg_months"] - b_base_neg
        delta_annual = v["annual_pct"] - results[("B_fee8", "baseline")]["summary"]["annual_pct"]
        print(f"  {var_slug}: neg {b_base_neg} -> {v['neg_months']} ({delta_neg:+d})  "
              f"annual delta: {delta_annual:+.1f}pp  max_loss: {v['max_loss_pct']:+.2f}%",
              flush=True)

    # ========================================================================
    # Identify which negative months changed (combo vs baseline, B fee=+8)
    # ========================================================================
    print(f"\n[NEG-MONTH DIFF] baseline vs combo (B fee=+8)...", flush=True)
    base_months = {(r["year"], r["month"]): r for r in
                   results[("B_fee8", "baseline")]["month_rows"]}
    combo_months = {(r["year"], r["month"]): r for r in
                    results[("B_fee8", "combo")]["month_rows"]}
    neg_diff_rows = []
    for k in sorted(base_months.keys()):
        b = base_months[k]
        c = combo_months[k]
        if b["skip"] or c["skip"]:
            continue
        b_neg = b["monthly_pct"] < 0
        c_neg = c["monthly_pct"] < 0
        if b_neg or c_neg or abs(b["monthly_pct"] - c["monthly_pct"]) >= 1.0:
            tag = ""
            if b_neg and not c_neg:
                tag = "RESCUED"
            elif not b_neg and c_neg:
                tag = "BROKE"
            elif b_neg and c_neg:
                tag = "STILL_NEG"
            else:
                tag = "DELTA"
            neg_diff_rows.append({
                "year": k[0], "month": k[1],
                "base_pct": b["monthly_pct"], "combo_pct": c["monthly_pct"],
                "base_n": b["n_taken"], "combo_n": c["n_taken"], "tag": tag,
            })
            print(f"  {k[0]}-{k[1]:02d}  base={b['monthly_pct']:+.2f}% (n={b['n_taken']})  "
                  f"combo={c['monthly_pct']:+.2f}% (n={c['n_taken']})  [{tag}]", flush=True)

    # ========================================================================
    # Verdict (primary B fee=+8 combo)
    # ========================================================================
    b_combo = results[("B_fee8", "combo")]
    s_combo = b_combo["summary"]
    mc_combo = b_combo["mandate"]
    primary_neg_ok = s_combo["neg_months"] <= 9
    primary_annual_ok = s_combo["annual_pct"] >= 1100.0
    primary_mandate_ok = mc_combo["n_pass"] >= 4

    if primary_neg_ok and primary_annual_ok and primary_mandate_ok:
        verdict = "PASS"
        verdict_text = (f"Neg ay {s_combo['neg_months']}/61 (mandate ≤9 PASS), "
                        f"annual +{s_combo['annual_pct']:.1f}% (≥1100 PASS), "
                        f"mandate {mc_combo['n_pass']}/5. SEC54.6d production candidate.")
    elif primary_neg_ok and s_combo["annual_pct"] >= 900.0:
        verdict = "WARN"
        verdict_text = (f"Neg ay {s_combo['neg_months']}/61 (PASS), "
                        f"annual +{s_combo['annual_pct']:.1f}% (∈ [900, 1100], trade-off). "
                        f"Lab paper trade adayı, principal review.")
    else:
        verdict = "FAIL"
        verdict_text = (f"Neg ay {s_combo['neg_months']}/61 "
                        f"(neg_ok={primary_neg_ok}), annual +{s_combo['annual_pct']:.1f}% "
                        f"(annual_ok={primary_annual_ok}, mandate {mc_combo['n_pass']}/5). "
                        f"Filter reject — alternative research gerek.")
    print(f"\n[VERDICT] {verdict}: {verdict_text}", flush=True)

    # ========================================================================
    # Markdown report
    # ========================================================================
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    out = []
    w = lambda s="": out.append(s + "\n")

    w("# SEC54.6d — Per-Strategy Regime Conditional Filter (Researcher Sprint)")
    w()
    w(f"**Researcher:** Head of Quantitative Research")
    w(f"**Date:** {now_str}")
    w(f"**Sprint:** SEC54.6d (YOL-C, Principal direktifi 2026-05-18 gece, overnight)")
    w(f"**Pre-reg:** `memory/researcher/hypotheses/2026-05-18-regime-conditional-filters.md`")
    w(f"**Pool:** `data/sec53_15m_pool_v11.pkl` "
      f"(SHA256 `{POOL_SHA256_EXPECTED[:16]}...`, TOP-4 × 10 sym, {len(pool):,} trade)")
    w(f"**Config:** `{RISK_YAML.name}` (SEC54.6 NEW YAML, C2+V5)")
    w(f"**Replay knobs:** risk_pct=0.02, pyramid (1.0, 1.5), max_conc=20, cooldown=0")
    w()
    w("---")
    w()
    w("## Executive Summary — NEG AY AZALTMA TABLOSU")
    w()
    w("| Variant | Annual (fee=+8) | Neg ay | Max loss | Mandate | Δ vs SEC54.6 |")
    w("|---|---:|---:|---:|---:|---|")
    for vslug in ["baseline", "F1", "F2", "F3", "F4", "combo"]:
        r = results[("B_fee8", vslug)]
        s = r["summary"]
        mc = r["mandate"]
        ref_a = SEC54_6_BASELINE["B_fee8"]["annual"]
        ref_n = SEC54_6_BASELINE["B_fee8"]["neg"]
        delta_a = s["annual_pct"] - ref_a
        delta_n = s["neg_months"] - ref_n
        w(f"| **{vslug}** | {s['annual_pct']:+.1f}% | {s['neg_months']} | "
          f"{s['max_loss_pct']:+.2f}% | {mc['n_pass']}/5 | "
          f"annual {delta_a:+.1f}pp / neg {delta_n:+d} |")
    w()
    w(f"**VERDICT: {verdict}** — {verdict_text}")
    w()
    w("---")
    w()
    w("## 1. Hipotez Pre-Reg Özet")
    w()
    w("4 filter (causal t-1 BTC daily lookup):")
    w()
    w("- **F1:** `anchored_vwap_reversal` → range (BTC ATR%<3% & |ret30|<3%) → SKIP")
    w("- **F2:** `brooks_failed_breakout` SHORT → bull (above_ema200 & ret30>+5%) → SKIP")
    w("- **F3:** `vsa_climax_test` LONG → bear (F&G<15 & ret30<-10%) → SKIP")
    w("- **F4:** `engulfing_continuation` → high_vol (vol_7d_ann>100%) → SKIP")
    w()
    w("Pre-registered gate (gevşek, Principal sign-off):")
    w("- PRIMARY neg ay ≤ 9 (mevcut 10)")
    w("- annual ≥ 1100% (erozyon < 20pp)")
    w("- max_loss ≥ -15% (gevşek)")
    w("- mandate ≥ 4/5")
    w()
    w("Stop criteria:")
    w("- 3+ filter null katkı → concentration RED")
    w("- pos≥+20% ay ≥3 düştü → false-positive RED")
    w("- annual erozyon > 30pp → trade-off RED")
    w()
    w("---")
    w()
    w("## 2. Filter Pre-Count (dry-run, kaç trade skip)")
    w()
    w("| Filter | Skip count | % of TOP-4 pool |")
    w("|---|---:|---:|")
    for fname in ["F1", "F2", "F3", "F4"]:
        n = pre_counts[fname]
        w(f"| {fname} | {n:,} | {100.0*n/len(pool):.2f}% |")
    w(f"| **COMBO (4 filter)** | {combo_stats['n_skipped_per_filter']['TOTAL']:,} | "
      f"{100.0*combo_stats['n_skipped_per_filter']['TOTAL']/len(pool):.2f}% |")
    w()
    w("Combo breakdown:")
    for fname in ["F1", "F2", "F3", "F4"]:
        w(f"- {fname}: {combo_stats['n_skipped_per_filter'][fname]:,} trade")
    w()
    w("---")
    w()
    w("## 3. Full Comparison Table")
    w()
    w("### 3.1 Fee = +8 bps (worst-case, Principal mandate)")
    w()
    w("| Variant | Annual | Mean monthly | Pos | Neg | Max gain | Max loss | CV | WF r-adj | Mandate |")
    w("|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
    for vslug in ["baseline", "F1", "F2", "F3", "F4", "combo"]:
        s = results[("B_fee8", vslug)]["summary"]
        mc = results[("B_fee8", vslug)]["mandate"]
        w(f"| {vslug} | {s['annual_pct']:+.1f}% | {s['mean_monthly_pct']:+.2f}% | "
          f"{s['pos_months']} | {s['neg_months']} | {s['max_gain_pct']:+.1f}% | "
          f"{s['max_loss_pct']:+.2f}% | {s['cv_pct']:.0f}% | {s['wf_mean_r_adj']:.2f} | "
          f"{mc['n_pass']}/5 |")
    w()
    w("### 3.2 Fee = +4 bps (realistic blend)")
    w()
    w("| Variant | Annual | Mean monthly | Pos | Neg | Max gain | Max loss | CV | WF r-adj | Mandate |")
    w("|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
    for vslug in ["baseline", "F1", "F2", "F3", "F4", "combo"]:
        s = results[("D_fee4", vslug)]["summary"]
        mc = results[("D_fee4", vslug)]["mandate"]
        w(f"| {vslug} | {s['annual_pct']:+.1f}% | {s['mean_monthly_pct']:+.2f}% | "
          f"{s['pos_months']} | {s['neg_months']} | {s['max_gain_pct']:+.1f}% | "
          f"{s['max_loss_pct']:+.2f}% | {s['cv_pct']:.0f}% | {s['wf_mean_r_adj']:.2f} | "
          f"{mc['n_pass']}/5 |")
    w()
    w("---")
    w()
    w("## 4. Per-Filter Contribution Analysis (B fee=+8)")
    w()
    w("**Hedef:** Hangi filter en çok neg ay azaltıyor? Tek başına edge taşıyor mu?")
    w()
    w("| Filter | Neg ay (baseline 10) | Δ neg | Annual delta vs baseline | Max loss | Yorum |")
    w("|---|---:|---:|---:|---:|---|")
    b_base_s = results[("B_fee8", "baseline")]["summary"]
    for fname in ["F1", "F2", "F3", "F4", "combo"]:
        v = results[("B_fee8", fname)]["summary"]
        delta_neg = v["neg_months"] - b_base_s["neg_months"]
        delta_ann = v["annual_pct"] - b_base_s["annual_pct"]
        yorum = ""
        if delta_neg < 0 and delta_ann >= -50:
            yorum = "+ neg ay azaldı, annual korundu"
        elif delta_neg < 0 and delta_ann < -100:
            yorum = "neg azaldı AMA annual ciddi düştü (trade-off)"
        elif delta_neg == 0:
            yorum = "null katkı (filter etki etmedi)"
        elif delta_neg > 0:
            yorum = "filter KÖTÜLEŞTİRDİ (false-positive)"
        w(f"| {fname} | {v['neg_months']} | {delta_neg:+d} | {delta_ann:+.1f}pp | "
          f"{v['max_loss_pct']:+.2f}% | {yorum} |")
    w()
    w("---")
    w()
    w("## 5. Negatif Ay Diff — Baseline vs Combo (B fee=+8)")
    w()
    if neg_diff_rows:
        w("| Year-Month | Baseline pct | Combo pct | Base n | Combo n | Tag |")
        w("|---|---:|---:|---:|---:|---|")
        for r in neg_diff_rows:
            w(f"| {r['year']}-{r['month']:02d} | {r['base_pct']:+.2f}% | "
              f"{r['combo_pct']:+.2f}% | {r['base_n']} | {r['combo_n']} | {r['tag']} |")
    else:
        w("Hiç ay değişmedi — filter pool'a dokunmadı.")
    w()
    w("Tag açıklama:")
    w("- **RESCUED:** baseline NEG → combo POS (filter işe yaradı)")
    w("- **BROKE:** baseline POS → combo NEG (filter KÖTÜLEŞTİRDİ)")
    w("- **STILL_NEG:** her ikisi de neg ama pct değişti")
    w("- **DELTA:** her ikisi de pos ama |delta| ≥ 1pp")
    w()
    w("---")
    w()
    w("## 6. False-Positive Check (Pos ≥+20% Ay Sayısı)")
    w()
    w("| Variant | ge20 ay (B fee=+8) | Δ vs baseline | ge20 ay (D fee=+4) | Δ |")
    w("|---|---:|---:|---:|---:|")
    b_base_ge20 = results[("B_fee8", "baseline")]["summary"]["ge20_months"]
    d_base_ge20 = results[("D_fee4", "baseline")]["summary"]["ge20_months"]
    for vslug in ["baseline", "F1", "F2", "F3", "F4", "combo"]:
        b_ge = results[("B_fee8", vslug)]["summary"]["ge20_months"]
        d_ge = results[("D_fee4", vslug)]["summary"]["ge20_months"]
        w(f"| {vslug} | {b_ge} | {b_ge-b_base_ge20:+d} | {d_ge} | {d_ge-d_base_ge20:+d} |")
    w()
    w("Stop criterion: Combo'da ge20 ay ≥3 düştüyse false-positive RED.")
    w()
    w("---")
    w()
    w("## 7. Baseline Parity Verify (SEC54.6 reference)")
    w()
    w(f"- SEC54.6 B_fee8 annual: **+{SEC54_6_BASELINE['B_fee8']['annual']:.1f}%**, "
      f"neg=**{SEC54_6_BASELINE['B_fee8']['neg']}**")
    w(f"- This run baseline (no filter) B_fee8 annual: "
      f"**{b_base['annual_pct']:+.1f}%**, neg=**{b_base['neg_months']}**")
    w(f"- Annual delta: {annual_delta:+.1f}pp (tol ±5pp) — "
      f"**{'PASS' if annual_delta<=5.0 else 'DRIFT'}**")
    w(f"- Neg parity: **{'PASS' if b_base['neg_months']==SEC54_6_BASELINE['B_fee8']['neg'] else 'DRIFT'}**")
    w()
    w("---")
    w()
    w("## 8. Filter Decision Sample (Lookahead-Paranoid Verify)")
    w()
    w(f"İlk {len(combo_stats['sample_logs'])} skip kararı (t-1 BTC daily lookup verify):")
    w()
    if combo_stats["sample_logs"]:
        w("| entry_ts | symbol | side | strategy | filter | lookup_date | atr_pct | ret_30 | above_ema200 | fng | vol_7d_ann |")
        w("|---|---|---|---|---|---|---:|---:|---:|---:|---:|")
        for s in combo_stats["sample_logs"]:
            atr_s = f"{s['atr_pct']:.2f}%" if s['atr_pct'] is not None else "?"
            ret_s = f"{s['ret_30']:.2f}%" if s['ret_30'] is not None else "?"
            ema_s = str(s['above_ema200']) if s['above_ema200'] is not None else "?"
            fng_s = f"{s['fng_value']:.0f}" if s['fng_value'] is not None else "?"
            vol_s = f"{s['vol_7d_ann']:.1f}%" if s['vol_7d_ann'] is not None else "?"
            w(f"| {s['entry_ts']} | {s['symbol']} | {s['side']} | {s['strategy']} | "
              f"{s['filter']} | {s['lookup_date']} | {atr_s} | {ret_s} | {ema_s} | "
              f"{fng_s} | {vol_s} |")
    w()
    w("Causal verify: `lookup_date = entry_ts.normalize() - 1 day` (forward-looking yok).")
    w()
    w("---")
    w()
    w("## 9. Mandate Compliance Detail (Combo, B fee=+8)")
    w()
    w("**SEC54.6d gevşek mandate (Principal sign-off):**")
    w("- annual ≥ 1100% (erozyon < 20pp)")
    w("- mean monthly ≥ 20%")
    w("- neg ay ≤ 9/61 PRIMARY")
    w("- max single loss ≥ -15% (gevşek)")
    w("- WF r-adj ≥ 12")
    w()
    for k, v in mc_combo["checks"].items():
        icon = "PASS" if v else "FAIL"
        w(f"- [{icon}] {k}")
    w()
    w("---")
    w()
    w("## 10. Verdict & Production Öneri")
    w()
    w(f"**Overall: {verdict}** — {verdict_text}")
    w()
    if verdict == "PASS":
        w("**Önerilen aksiyon:**")
        w("1. SEC54.6d production candidate — `risk_phoenix_scalp_15m_c2v5_final.yaml` "
          "REGIME_FILTER_ENABLED block ekle.")
        w("2. Filter engine'i live'a port et (`src/price_action/risk/regime_filter.py` "
          "extension, mevcut RegimeFilter sınıfına strateji-bazlı method).")
        w("3. Lab paper trade 14g — filter decision log canlı vs backtest parity verify.")
        w("4. Lookahead audit Engineering ticket: t-1 BTC daily snapshot scheduler "
          "(0:01 UTC daily refresh).")
    elif verdict == "WARN":
        w("**Önerilen aksiyon:**")
        w("1. Lab paper trade 7g — annual erozyon canlı vs backtest karşılaştır.")
        w("2. Threshold tuning sprint (overfit riski, Bonferroni-aware).")
        w("3. Principal review: trade-off kabul edilebilir mi?")
    else:
        w("**Önerilen aksiyon:**")
        w("1. SEC54.6d archive — filter design'ı reject.")
        w("2. Alternative araştırma: side-cond DD genişletme veya per-strategy halt.")
        w("3. Memory note: HYP-REGIME serisi 4. RED (per-strategy targeted da yetmedi).")
    w()
    w("---")
    w()
    w("## 11. Files")
    w()
    for fee_slug, _ in fee_scenarios:
        for vslug, _ in variants:
            r = results[(fee_slug, vslug)]
            w(f"- `{Path(r['csv_month']).name}` — per-month {vslug} {fee_slug}")
    w(f"- `sec54_6d_filter_decisions_sample.csv` — sample skip decisions (causal verify)")
    w()
    w("---")
    w()
    w(f"*Generated: {now_str} by SEC54.6d regime_filter_replay sprint (overnight)*")

    REPORT.write_text("".join(out), encoding="utf-8")
    print(f"\n[REPORT] {REPORT}", flush=True)
    print("[SEC54.6d] DONE", flush=True)


if __name__ == "__main__":
    main()
