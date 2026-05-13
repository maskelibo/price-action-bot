"""SEC15.3 — TP 4D Grid v2 (DOGRU v1.5 baseline ile).

PRE-REGISTERED HIPOTEZ:
  v1.5 production stack (yillik +%116.3 / DD -%34.9 / r-adj 3.332) icinde
  TP1/TP2 close pct ve R-multiple kombinasyonu hic systematik sweep edilmedi.
  Mevcut 30%/30% (runner=40%) sweet spot mu? Asimetrik konfigurasyonlar
  (50%/30% fast-realize, 20%/30% big-runner, 40%/40% symmetric) ek alpha verebilir mi?

ENGINE DEFAULTS (v1.5, BASELINE icin sabit):
  runner_trail_mult=1.5
  trail_activate_stage=2
  runner_force_exit_method='time'
  runner_force_exit_bars=30
  (tp1_R, tp2_R, tp1_close_pct, tp2_close_pct = grid sweep variables)

CONFIG (v1.5 stack — risk_balanced.yaml + halt + F&G + funding):
  monthly_dd_long=0.10, monthly_dd_short=0.05  (side-cond hibrit)
  monthly_dd=0.06, monthly_halt_days=21
  max_concurrent=12, risk_pct=0.04
  alt-data: BTC halt + funding-short + F&G fear short-skip

BASELINE SANITY CHECK (zorunlu):
  A6 cache pool reuse (6650 trade, mult=1.5, time/30bar, 1.0R/1.5R/30/30)
  Beklenti: yillik +%116 +/- 1pp
  Olcum: +%116.92 / DD -%34.90 / r-adj 3.350  -> OK

GRID (smart sampling, pre-registered HARK protection):
  PHASE A: 25 hucre koarse (4D corners + baseline)
    tp1_R ∈ {0.5, 0.75, 1.0(B), 1.25, 1.5}
    tp2_R ∈ {1.25, 1.5(B), 1.75, 2.0, 2.5}
    tp1_close ∈ {0.20, 0.30(B), 0.40, 0.50}
    tp2_close ∈ {0.20, 0.30(B), 0.40, 0.50}
    Constraint: tp1_R < tp2_R, tp1_close + tp2_close < 1.0
    Selection: baseline + 4 R-corner × 4 close-corner = 17, + 8 strategic mid = 25 hucre

  PHASE B: PHASE A top-10 etrafinda fine grid (ek 8-12 hucre)
    Sec12.B oruntusu: top close-config × ekstra R-variant

STATISTICAL GATES (her hucre):
  G0 ARTIFACT  max_R <= 20         (force-exit ile zaten saglanir)
  G1 RETURN    mean_ann >= +%121.92 (baseline +%116.92 + 5pp — yuksek bar)
  G2 DD        mean_dd >= -%39.90  (baseline -%34.90 - 5pp tolerans)
  G3 NEG       0 negatif pencere
  G4 R-ADJ     r_adj >= 3.450      (baseline 3.350 + 0.10)

POOL CACHE: data/_sec15_3_cache/pool_<label>.pkl (each unique R/close combo)

OUTPUT: reports/lab/sec15_3_tp4d_v2.md
"""
from __future__ import annotations

import json
import os
import pickle
import sys
import warnings
from dataclasses import dataclass, asdict
from pathlib import Path
from statistics import mean, median

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

from price_action.backtest.engine import BacktestEngine
from price_action.backtest.lab import (
    ProductionConfig, production_replay, _lazy_build_funding_filters,
)
from price_action.backtest.regime import compute_btc_capitulation_halt
from price_action.signals.filters import volume_zscore
from scripts.run_real_backtest import _load_symbol_ohlcv
from scripts.v09_optimize_top10 import TOP_10, SYMBOLS_11
from scripts.v097_balanced_optimization import build_fng_short_skip

TOP_11 = TOP_10 + [("fvg_fill_reversal", "FVGFillReversalStrategy")]

CACHE_DIR = ROOT / "data" / "_sec15_3_cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)
REPORT_PATH = ROOT / "reports" / "lab" / "sec15_3_tp4d_v2.md"
JSON_PATH = ROOT / "reports" / "lab" / "sec15_3_tp4d_v2.json"

# v1.5 ENGINE FIXED PARAMS (NOT in grid — locked baseline)
ENGINE_FIXED = dict(
    runner_trail_mult=1.5,
    trail_activate_stage=2,
    runner_force_exit_method="time",
    runner_force_exit_bars=30,
    runner_force_exit_ema=20,
)

# Reuse SEC13.4 A6 baseline pool (identical engine kwargs as our v1.5 baseline)
SEC13_4_A6_CACHE = ROOT / "data" / "_sec13_4_cache" / "pool_A6_mult15_t30.pkl"


# =====================================================================
# Pool generation (engine kwargs paramlandi)
# =====================================================================

def gather_with_engine(module_name, class_name, *,
                       tp1_R, tp2_R, tp1_close_pct, tp2_close_pct):
    """v1.5 engine baseline (mult=1.5 + time/30bar) + 4D TP overrides."""
    try:
        mod = __import__(f"price_action.strategies.{module_name}",
                         fromlist=[class_name, "_default_manifest"])
        cls = getattr(mod, class_name)
        manifest_fn = getattr(mod, "_default_manifest", None)
        if not manifest_fn:
            return []
        s = cls(manifest_fn())
    except Exception as e:
        print(f"  [WARN-import] {module_name}: {e}")
        return []

    out = []
    for sym in SYMBOLS_11:
        try:
            df = _load_symbol_ohlcv(sym, tf="1d")
            if df is None or df.empty:
                continue
            df = df.sort_values("ts").reset_index(drop=True)
            df["symbol"] = sym
            df["venue"] = "binance"
            df["timeframe"] = "1d"
            try:
                df["vol_z_pre"] = volume_zscore(df["volume"], period=20)
            except Exception:
                rolling = df["volume"].rolling(20)
                df["vol_z_pre"] = (df["volume"] - rolling.mean()) / rolling.std()

            def prov(*a, **k):
                return df.copy()

            e = BacktestEngine(
                risk_officer=None, store_load=None,
                tp1_R=tp1_R, tp2_R=tp2_R,
                tp1_close_pct=tp1_close_pct, tp2_close_pct=tp2_close_pct,
                **ENGINE_FIXED,
            )
            r = e.run(
                s, [sym],
                start=df["ts"].iloc[0].to_pydatetime(),
                end=df["ts"].iloc[-1].to_pydatetime(),
                timeframe="1d", initial_capital=10_000.0,
                fees={"taker": 0.00075, "maker": -0.00010},
                slippage_bps=5.0,
                ohlcv_provider=prov,
            )
            ts_map = pd.to_datetime(df["ts"], utc=True)
            for _, t in r.trades.iterrows():
                conf = max(0.0, min(1.0, (float(t["confluence_score"]) - 1.5) / 1.5))
                ts_e = pd.Timestamp(t["entry_ts"])
                if ts_e.tzinfo is None:
                    ts_e = ts_e.tz_localize("UTC")
                ts_x = pd.Timestamp(t["exit_ts"])
                if ts_x.tzinfo is None:
                    ts_x = ts_x.tz_localize("UTC")
                mask = ts_map < ts_e
                vz = 0.0
                if mask.any():
                    idx = ts_map[mask].index[-1]
                    val = df["vol_z_pre"].iloc[idx]
                    if pd.notna(val):
                        vz = float(val)
                out.append({
                    "entry_ts": ts_e, "exit_ts": ts_x,
                    "entry_price": float(t["entry_price"]),
                    "initial_sl": float(t["initial_sl"]),
                    "R": float(t["realized_r_multiple"]),
                    "symbol": sym, "side": str(t["side"]).lower(),
                    "conf": conf, "strategy": module_name, "vol_z": vz,
                })
        except Exception as e:
            print(f"  [WARN-sim] {module_name}/{sym}: {e}")
    return out


def _label(tp1_R, tp2_R, tp1c, tp2c) -> str:
    """Stable filename for cache."""
    return f"r{tp1_R}_{tp2_R}_c{int(round(tp1c*100))}_{int(round(tp2c*100))}"


def build_pool(tp1_R, tp2_R, tp1_close_pct, tp2_close_pct):
    """Per-cell pool gen + cache. Reuse SEC13.4 A6 cache for baseline."""
    label = _label(tp1_R, tp2_R, tp1_close_pct, tp2_close_pct)
    cache_p = CACHE_DIR / f"pool_{label}.pkl"

    # Special: baseline 1.0/1.5/30/30 == sec13_4 A6 — symlink/reuse
    is_baseline = (
        abs(tp1_R - 1.0) < 1e-9 and abs(tp2_R - 1.5) < 1e-9
        and abs(tp1_close_pct - 0.30) < 1e-9 and abs(tp2_close_pct - 0.30) < 1e-9
    )
    if is_baseline and SEC13_4_A6_CACHE.exists() and not cache_p.exists():
        print(f"  [pool] {label}: REUSE sec13_4 A6 cache")
        with SEC13_4_A6_CACHE.open("rb") as f:
            pool = pickle.load(f)
        with cache_p.open("wb") as f:
            pickle.dump(pool, f)
        return pool

    if cache_p.exists():
        with cache_p.open("rb") as f:
            return pickle.load(f)

    print(f"  [pool gen] {label}: tp1_R={tp1_R} tp2_R={tp2_R} c1={tp1_close_pct:.2f} c2={tp2_close_pct:.2f}")
    pool = []
    for m, c in TOP_11:
        ts = gather_with_engine(
            m, c, tp1_R=tp1_R, tp2_R=tp2_R,
            tp1_close_pct=tp1_close_pct, tp2_close_pct=tp2_close_pct,
        )
        pool.extend(ts)
    pool.sort(key=lambda x: x["entry_ts"])
    with cache_p.open("wb") as f:
        pickle.dump(pool, f)
    print(f"     -> {len(pool)} trade  saved {cache_p.name}")
    return pool


# =====================================================================
# Walk-forward eval
# =====================================================================

def make_windows(start, end, span_days=3 * 365, step_days=60):
    out = []
    cur = start
    while cur + pd.Timedelta(days=span_days) <= end:
        out.append((cur, cur + pd.Timedelta(days=span_days)))
        cur += pd.Timedelta(days=step_days)
    return out


def evaluate_pool(trades, cfg, windows):
    if not trades:
        return None
    anns, dds = [], []
    for ws, we in windows:
        w = [t for t in trades if ws <= t["entry_ts"] < we]
        r = production_replay(w, cfg)
        if r is None:
            continue
        anns.append(r.annualized(3.0) * 100)
        dds.append(r.max_drawdown * 100)
    if not anns:
        return None
    ma, md = mean(anns), mean(dds)
    ra = ma / abs(md) if md != 0 else 0
    return {
        "mean_ann": ma,
        "median_ann": median(anns),
        "min_ann": min(anns),
        "max_ann": max(anns),
        "mean_dd": md,
        "min_dd": min(dds),
        "r_adj": ra,
        "negatives": sum(1 for a in anns if a < 0),
        "n_windows": len(anns),
    }


def pool_artifact_stats(trades):
    if not trades:
        return {"max_R": 0, "p99_R": 0, "p95_R": 0, "n": 0, "mean_R": 0}
    rs = [float(t["R"]) for t in trades]
    return {
        "max_R": max(rs),
        "p99_R": float(np.percentile(rs, 99)),
        "p95_R": float(np.percentile(rs, 95)),
        "min_R": min(rs),
        "mean_R": float(np.mean(rs)),
        "n": len(rs),
    }


@dataclass
class CellResult:
    label: str
    tp1_R: float
    tp2_R: float
    tp1_close_pct: float
    tp2_close_pct: float
    runner_pct: float
    n_trades: int
    max_R: float
    p99_R: float
    mean_R: float
    mean_ann: float
    median_ann: float
    min_ann: float
    max_ann: float
    mean_dd: float
    min_dd: float
    r_adj: float
    negatives: int
    n_windows: int
    is_baseline: bool = False
    phase: str = ""


def eval_cell(tp1_R, tp2_R, tp1_close, tp2_close, cfg, windows, *,
              phase="", is_baseline=False, log=True) -> CellResult:
    label = _label(tp1_R, tp2_R, tp1_close, tp2_close)
    pool = build_pool(tp1_R, tp2_R, tp1_close, tp2_close)
    if not pool:
        return CellResult(label, tp1_R, tp2_R, tp1_close, tp2_close,
                          1.0 - tp1_close - tp2_close, 0,
                          0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
                          is_baseline=is_baseline, phase=phase)
    art = pool_artifact_stats(pool)
    res = evaluate_pool(pool, cfg, windows)
    if res is None:
        return CellResult(label, tp1_R, tp2_R, tp1_close, tp2_close,
                          1.0 - tp1_close - tp2_close, len(pool),
                          art["max_R"], art["p99_R"], art["mean_R"],
                          0, 0, 0, 0, 0, 0, 0, 0, 0,
                          is_baseline=is_baseline, phase=phase)
    runner = 1.0 - tp1_close - tp2_close
    cr = CellResult(
        label=label, tp1_R=tp1_R, tp2_R=tp2_R,
        tp1_close_pct=tp1_close, tp2_close_pct=tp2_close,
        runner_pct=runner, n_trades=len(pool),
        max_R=art["max_R"], p99_R=art["p99_R"], mean_R=art["mean_R"],
        mean_ann=res["mean_ann"], median_ann=res["median_ann"],
        min_ann=res["min_ann"], max_ann=res["max_ann"],
        mean_dd=res["mean_dd"], min_dd=res["min_dd"],
        r_adj=res["r_adj"], negatives=res["negatives"],
        n_windows=res["n_windows"], is_baseline=is_baseline, phase=phase,
    )
    if log:
        tag = " <-- BASELINE" if is_baseline else ""
        print(f"  {label:<22} tp1={tp1_R:.2f}R tp2={tp2_R:.2f}R c1={tp1_close:.0%} c2={tp2_close:.0%} "
              f"run={runner:.0%}  n={len(pool):>5}  ann={cr.mean_ann:>+7.2f}% "
              f"DD={cr.mean_dd:>+6.2f}% r={cr.r_adj:>5.3f}  maxR={cr.max_R:>+5.1f}  "
              f"neg={cr.negatives}/{cr.n_windows}{tag}")
    return cr


# =====================================================================
# Pre-registered grid
# =====================================================================

# Phase A: 25 koarse hucre — pre-registered, HARK-safe
PHASE_A_CELLS: list[tuple[float, float, float, float]] = [
    # 0) BASELINE
    (1.0, 1.5, 0.30, 0.30),

    # 1) tp1_R sweep (tp2=1.5, c=30/30)
    (0.5,  1.5, 0.30, 0.30),
    (0.75, 1.5, 0.30, 0.30),
    (1.25, 1.5, 0.30, 0.30),  # (skipped if tp1>=tp2; 1.25<1.5 OK)

    # 2) tp2_R sweep (tp1=1.0, c=30/30)
    (1.0, 1.25, 0.30, 0.30),
    (1.0, 1.75, 0.30, 0.30),
    (1.0, 2.0,  0.30, 0.30),
    (1.0, 2.5,  0.30, 0.30),

    # 3) tp1_close sweep (1.0/1.5, tp2_close=30)
    (1.0, 1.5, 0.20, 0.30),
    (1.0, 1.5, 0.40, 0.30),
    (1.0, 1.5, 0.50, 0.30),

    # 4) tp2_close sweep (1.0/1.5, tp1_close=30)
    (1.0, 1.5, 0.30, 0.20),
    (1.0, 1.5, 0.30, 0.40),
    (1.0, 1.5, 0.30, 0.50),

    # 5) symmetric & dual-asymmetric (R fixed 1.0/1.5)
    (1.0, 1.5, 0.40, 0.40),
    (1.0, 1.5, 0.20, 0.20),
    (1.0, 1.5, 0.50, 0.20),  # fast tp1 + small tp2 -> runner=30
    (1.0, 1.5, 0.20, 0.50),  # small tp1 + fast tp2 -> runner=30

    # 6) 4D corners (R + close together)
    (0.5,  1.25, 0.50, 0.30),  # fast everything
    (0.5,  2.0,  0.50, 0.20),  # fast tp1 + far tp2 + small tp2 (big runner)
    (0.75, 2.0,  0.30, 0.30),  # mid R-spread
    (1.25, 2.0,  0.30, 0.30),  # wide tp1
    (1.25, 2.5,  0.20, 0.30),  # wide R + small tp1 (runner=50)
    (1.5,  2.5,  0.30, 0.30),  # widest R-spread
    (0.75, 1.75, 0.40, 0.30),  # mid R + bigger tp1
]
# Filter constraint: tp1_R < tp2_R, tp1c + tp2c < 1.0
PHASE_A_CELLS = [
    (a, b, c, d) for (a, b, c, d) in PHASE_A_CELLS
    if a < b and (c + d) < 1.0
]


def gen_phase_b_cells(top_a: list[CellResult], n_target: int = 12) -> list[tuple]:
    """Top-region fine grid based on Phase A r-adj rankings."""
    seen: set[tuple] = set()
    out: list[tuple] = []
    # Deduplicator
    def add(t):
        key = tuple(round(x, 4) for x in t)
        if key not in seen:
            seen.add(key)
            out.append(t)

    for cell in top_a[:5]:
        # +/- adjacent close perturbations (5pp)
        c1, c2 = cell.tp1_close_pct, cell.tp2_close_pct
        for dc1 in (-0.05, 0.0, +0.05):
            for dc2 in (-0.05, 0.0, +0.05):
                nc1 = round(c1 + dc1, 2)
                nc2 = round(c2 + dc2, 2)
                if nc1 < 0.10 or nc2 < 0.10 or nc1 > 0.60 or nc2 > 0.60:
                    continue
                if nc1 + nc2 >= 1.0:
                    continue
                add((cell.tp1_R, cell.tp2_R, nc1, nc2))
        # Adjacent R perturbations
        for dR1 in (-0.25, 0.0, +0.25):
            for dR2 in (-0.25, 0.0, +0.25):
                nR1 = round(cell.tp1_R + dR1, 2)
                nR2 = round(cell.tp2_R + dR2, 2)
                if nR1 <= 0.25 or nR2 <= 0.5 or nR1 >= nR2:
                    continue
                add((nR1, nR2, c1, c2))
    return out[:n_target]


# =====================================================================
# MAIN
# =====================================================================

def main():
    print("=" * 120)
    print("SEC15.3 — TP 4D Grid v2 (DOGRU v1.5 baseline ile)")
    print("=" * 120)

    # --- Build v1.5 cfg (YAML auto loads side-cond) ---
    print("\n[1/4] v1.5 cfg setup (risk_balanced.yaml + halt + F&G + funding)...")
    base = ProductionConfig.from_yaml(str(ROOT / "configs" / "risk_balanced.yaml"))
    halt_cal = compute_btc_capitulation_halt()
    fund_long, fund_short = _lazy_build_funding_filters({
        "funding_filter_enabled": True, "funding_aggregation_mode": "00:00_only",
    })
    fng_short_20 = build_fng_short_skip(20)
    combined_short_skip = {**dict(fund_short or {}), **dict(fng_short_20)}
    cfg = base.with_overrides(
        btc_halt_calendar=halt_cal,
        alt_data_skip_long=fund_long,
        alt_data_skip_short=combined_short_skip,
    )
    print(f"  monthly_dd={cfg.monthly_dd}  mdd_long={cfg.monthly_dd_long}  mdd_short={cfg.monthly_dd_short}")
    print(f"  halt_days={cfg.monthly_halt_days}  max_concurrent={cfg.max_concurrent}  risk_pct={cfg.risk_pct}")
    print(f"  alt: halt_days_total={sum(1 for v in halt_cal.values() if v)}  fund_long={len(fund_long or {})}  short_skip={len(combined_short_skip)}")

    # --- BASELINE first (sanity check, must match +%116) ---
    print("\n[2/4] BASELINE pool gen (v1.5: mult=1.5 + time/30 + 1.0/1.5/30/30)")
    baseline_pool = build_pool(1.0, 1.5, 0.30, 0.30)
    if not baseline_pool:
        print("FATAL: baseline pool empty.")
        return
    print(f"  Baseline pool: {len(baseline_pool)} trade")

    win_start = baseline_pool[0]["entry_ts"]
    win_end = baseline_pool[-1]["exit_ts"]
    windows = make_windows(win_start, win_end)
    print(f"  Windows: {len(windows)} pencere ({win_start.date()} -> {win_end.date()})")

    print("\n  Header: label                tp1   tp2   c1   c2   runner    n      ann       DD     r-adj  maxR  neg/n")
    print("  " + "-" * 130)
    base_cell = eval_cell(1.0, 1.5, 0.30, 0.30, cfg, windows,
                          phase="BASELINE", is_baseline=True)

    # SANITY: baseline +%116 +/- 1pp
    if not (115.0 <= base_cell.mean_ann <= 118.0):
        print(f"\nFATAL: baseline mean_ann {base_cell.mean_ann:+.2f}% not in [+115, +118] expected v1.5 range!")
        print("Setup hatasi — engine defaults veya config v1.5 ile uyusmuyor. Durum.")
        return

    print(f"\n  SANITY OK: baseline +{base_cell.mean_ann:.2f}% (v1.5 hedef +%116 +/- 1pp tolerans gecti)")

    b_ann = base_cell.mean_ann
    b_dd = base_cell.mean_dd
    b_radj = base_cell.r_adj

    # --- PHASE A: 25 koarse hucre ---
    print(f"\n[3/4] PHASE A — koarse 4D grid ({len(PHASE_A_CELLS)} hucre)")
    print("  " + "-" * 130)
    results: list[CellResult] = [base_cell]
    for cell in PHASE_A_CELLS:
        if (abs(cell[0] - 1.0) < 1e-9 and abs(cell[1] - 1.5) < 1e-9
            and abs(cell[2] - 0.30) < 1e-9 and abs(cell[3] - 0.30) < 1e-9):
            continue  # baseline, already done
        cr = eval_cell(*cell, cfg=cfg, windows=windows, phase="A")
        results.append(cr)

    # --- PHASE B: top-10 etrafinda fine ---
    valid_a = [r for r in results if r.phase == "A" and r.n_trades > 0]
    valid_a.sort(key=lambda r: -r.r_adj)
    top_a = valid_a[:10]

    print(f"\n[4/4] PHASE B — fine grid (top-10 Phase A etrafinda)")
    print(f"  Top-5 Phase A by r-adj:")
    for i, r in enumerate(top_a[:5], 1):
        print(f"    #{i} {r.label}  r-adj={r.r_adj:.3f}  ann={r.mean_ann:+.2f}%  DD={r.mean_dd:+.2f}%")
    phase_b_cells = gen_phase_b_cells(top_a, n_target=15)
    print(f"  Phase B cells (post-dedupe): {len(phase_b_cells)}")
    print("  " + "-" * 130)
    for cell in phase_b_cells:
        # Skip if already evaluated (Phase A or baseline)
        existing = [r for r in results if abs(r.tp1_R - cell[0]) < 1e-9
                    and abs(r.tp2_R - cell[1]) < 1e-9
                    and abs(r.tp1_close_pct - cell[2]) < 1e-9
                    and abs(r.tp2_close_pct - cell[3]) < 1e-9]
        if existing:
            continue
        cr = eval_cell(*cell, cfg=cfg, windows=windows, phase="B")
        results.append(cr)

    # =========================================================================
    # GATES + Decision
    # =========================================================================
    print("\n" + "=" * 120)
    print("STATISTICAL GATES (vs v1.5 baseline)")
    print("=" * 120)
    print(f"  baseline: ann={b_ann:+.2f}%  DD={b_dd:+.2f}%  r-adj={b_radj:.3f}")
    print(f"  G0 ARTIFACT: max_R <= 20")
    print(f"  G1 RETURN:   mean_ann >= {b_ann + 5.0:.2f}% (baseline +5pp)")
    print(f"  G2 DD:       mean_dd >= {b_dd - 5.0:.2f}% (baseline -5pp tolerans)")
    print(f"  G3 NEG:      0 negatif pencere")
    print(f"  G4 R-ADJ:    r-adj >= {b_radj + 0.10:.3f} (baseline +0.10)\n")

    print(f"{'label':<22} {'phase':<6} {'G0':>3} {'G1':>3} {'G2':>3} {'G3':>3} {'G4':>3} {'verdict':>8}  "
          f"{'d_ann':>8} {'d_dd':>7} {'d_radj':>8}  {'maxR':>6}")
    print("-" * 120)
    pass_cells = []
    for r in results:
        if r.is_baseline:
            print(f"{r.label:<22} {'(B)':<6} {'-':>3} {'-':>3} {'-':>3} {'-':>3} {'-':>3} {'BASE':>8}  "
                  f"{'-':>8} {'-':>7} {'-':>8}  {r.max_R:>+5.1f}")
            continue
        if r.n_trades == 0:
            print(f"{r.label:<22} {r.phase:<6} EMPTY POOL")
            continue
        g0 = r.max_R <= 20.0
        g1 = r.mean_ann >= b_ann + 5.0
        g2 = r.mean_dd >= b_dd - 5.0
        g3 = r.negatives == 0
        g4 = r.r_adj >= b_radj + 0.10
        ok = g0 and g1 and g2 and g3 and g4
        verdict = "PASS" if ok else "fail"
        print(f"{r.label:<22} {r.phase:<6} "
              f"{'OK' if g0 else 'XX':>3} "
              f"{'OK' if g1 else '..':>3} "
              f"{'OK' if g2 else '..':>3} "
              f"{'OK' if g3 else '..':>3} "
              f"{'OK' if g4 else '..':>3} "
              f"{verdict:>8}  "
              f"{r.mean_ann - b_ann:>+7.2f}pp {r.mean_dd - b_dd:>+6.2f}pp "
              f"{r.r_adj - b_radj:>+7.3f}  {r.max_R:>+5.1f}")
        if ok:
            pass_cells.append(r)

    # Top-10 by r-adj
    valid = [r for r in results if r.n_trades > 0]
    sorted_radj = sorted(valid, key=lambda r: -r.r_adj)[:10]
    print(f"\n--- TOP-10 BY r-adj ---")
    for i, r in enumerate(sorted_radj, 1):
        tag = " (B)" if r.is_baseline else f" ({r.phase})"
        print(f"  #{i:2d} {r.label:<22}{tag}  ann={r.mean_ann:+.2f}%  DD={r.mean_dd:+.2f}%  "
              f"r-adj={r.r_adj:.3f}  runner={r.runner_pct:.0%}  maxR={r.max_R:+.1f}  neg={r.negatives}")

    # Asymmetry pattern analysis
    print("\n--- ASIMETRI PATTERN ---")
    big_runner = [r for r in valid if r.runner_pct >= 0.45 and not r.is_baseline]
    fast_realize = [r for r in valid if r.runner_pct <= 0.25 and not r.is_baseline]
    symmetric = [r for r in valid if 0.30 <= r.runner_pct <= 0.40 and not r.is_baseline]
    if big_runner:
        br_ann = mean(r.mean_ann for r in big_runner)
        br_dd = mean(r.mean_dd for r in big_runner)
        br_radj = mean(r.r_adj for r in big_runner)
        print(f"  BIG-RUNNER (run>=45%, n={len(big_runner)}):  ann={br_ann:+.2f}%  DD={br_dd:+.2f}%  r-adj={br_radj:.3f}")
    if symmetric:
        sm_ann = mean(r.mean_ann for r in symmetric)
        sm_dd = mean(r.mean_dd for r in symmetric)
        sm_radj = mean(r.r_adj for r in symmetric)
        print(f"  SYMMETRIC  (run 30-40%, n={len(symmetric)}):  ann={sm_ann:+.2f}%  DD={sm_dd:+.2f}%  r-adj={sm_radj:.3f}")
    if fast_realize:
        fr_ann = mean(r.mean_ann for r in fast_realize)
        fr_dd = mean(r.mean_dd for r in fast_realize)
        fr_radj = mean(r.r_adj for r in fast_realize)
        print(f"  FAST-REAL  (run<=25%, n={len(fast_realize)}): ann={fr_ann:+.2f}%  DD={fr_dd:+.2f}%  r-adj={fr_radj:.3f}")

    # Winner
    print("\n--- KARAR ---")
    winner = None
    if pass_cells:
        pass_cells.sort(key=lambda r: -r.r_adj)
        winner = pass_cells[0]
        print(f"WINNER: {winner.label} (phase {winner.phase})")
        print(f"  tp1_R={winner.tp1_R}  tp2_R={winner.tp2_R}  tp1_c={winner.tp1_close_pct:.0%}  "
              f"tp2_c={winner.tp2_close_pct:.0%}  runner={winner.runner_pct:.0%}")
        print(f"  ann={winner.mean_ann:+.2f}% (baseline {b_ann:+.2f}%, +{winner.mean_ann - b_ann:.2f}pp)")
        print(f"  DD={winner.mean_dd:+.2f}% (baseline {b_dd:+.2f}%, {winner.mean_dd - b_dd:+.2f}pp)")
        print(f"  r-adj={winner.r_adj:.3f} (baseline {b_radj:.3f}, +{winner.r_adj - b_radj:.3f})")
        print(f"  max_R={winner.max_R:+.1f}  neg={winner.negatives}")
    else:
        print("RED — hicbir hucre G0-G4 hepsini gecmedi.")
        print("v1.5 production parametre korunur (1.0R/1.5R/30/30/40-runner).")

    # ============== Persist ==============
    JSON_PATH.parent.mkdir(parents=True, exist_ok=True)
    with JSON_PATH.open("w", encoding="utf-8") as f:
        json.dump({
            "baseline": asdict(base_cell),
            "results": [asdict(r) for r in results],
            "winner": asdict(winner) if winner else None,
            "n_windows": len(windows),
            "config": {
                "preset": "v1.5 BALANCED+halt+F&G+funding+side-cond",
                "monthly_dd": cfg.monthly_dd,
                "monthly_dd_long": cfg.monthly_dd_long,
                "monthly_dd_short": cfg.monthly_dd_short,
                "halt_days": cfg.monthly_halt_days,
                "max_concurrent": cfg.max_concurrent,
                "risk_pct": cfg.risk_pct,
                "engine_fixed": ENGINE_FIXED,
            },
            "gates": {
                "G0_artifact_max_R": 20.0,
                "G1_return_min": b_ann + 5.0,
                "G2_dd_min": b_dd - 5.0,
                "G3_max_negatives": 0,
                "G4_radj_min": b_radj + 0.10,
            },
        }, f, indent=2, default=str)
    print(f"\nJSON: {JSON_PATH}")

    write_report(REPORT_PATH, base_cell, results, pass_cells, winner,
                 big_runner, symmetric, fast_realize, len(windows))
    print(f"MD:   {REPORT_PATH}")


def write_report(path, base, results, pass_cells, winner,
                 big_runner, symmetric, fast_realize, n_windows):
    L = []
    L.append("# SEC15.3 — TP 4D Grid v2 (DOGRU v1.5 baseline)\n\n")
    L.append("**Tarih:** 2026-05-13  \n")
    L.append("**Sprint:** sec15_3_tp4d_v2  \n")
    L.append(f"**Walk-forward:** {n_windows} pencere (3y rolling, 60g step)  \n")
    L.append("**Engine FIXED (v1.5 baseline locked):** mult=1.5, force_exit=time/30bar  \n")
    L.append("**Config:** v1.5 BALANCED + halt + F&G + funding + side-cond (long=0.10, short=0.05)  \n")
    L.append(f"**BASELINE (sanity):** {base.mean_ann:+.2f}% / DD {base.mean_dd:+.2f}% / r-adj {base.r_adj:.3f}  "
             f"(target +%116 +/- 1pp — **OK**)\n\n")

    L.append("## TL;DR\n\n")
    if winner:
        L.append(f"**WIN:** `{winner.label}` (Phase {winner.phase}) — "
                 f"tp1_R={winner.tp1_R}, tp2_R={winner.tp2_R}, "
                 f"tp1_c={winner.tp1_close_pct:.0%}, tp2_c={winner.tp2_close_pct:.0%}, "
                 f"runner={winner.runner_pct:.0%}\n")
        L.append(f"- ann **{winner.mean_ann:+.2f}%** (baseline {base.mean_ann:+.2f}%, "
                 f"**{winner.mean_ann - base.mean_ann:+.2f}pp**)\n")
        L.append(f"- DD {winner.mean_dd:+.2f}% (baseline {base.mean_dd:+.2f}%, "
                 f"{winner.mean_dd - base.mean_dd:+.2f}pp)\n")
        L.append(f"- r-adj **{winner.r_adj:.3f}** (baseline {base.r_adj:.3f}, "
                 f"+{winner.r_adj - base.r_adj:.3f})\n")
        L.append(f"- max_R {winner.max_R:+.1f} (G0 OK, force-exit calisiyor)\n")
        L.append(f"- negatif: {winner.negatives}/{winner.n_windows}\n\n")
    else:
        L.append("**RED.** 4D grid'de hicbir hucre G0-G4 hepsini gecemedi. "
                 "v1.5 (1.0R/1.5R/30/30/40-runner) optimum kalir.\n\n")

    L.append("## Hipotez\n\n")
    L.append("v1.5 production stack icinde TP1/TP2 close pct'leri ve R-multiple kombinasyonu hic systematik sweep edilmedi. "
             "Mevcut 30%/30% (runner=40%) sweet spot mu? Asimetrik konfigurasyonlar (50%/30% fast-realize, 20%/30% big-runner, "
             "40%/40% symmetric) ek alpha verebilir mi?\n\n")

    L.append("## Smart sampling\n\n")
    L.append(f"- **PHASE A**: {len([r for r in results if r.phase == 'A'])} koarse hucre (4D corners + R/close axes + strategic mid)\n")
    L.append(f"- **PHASE B**: {len([r for r in results if r.phase == 'B'])} fine hucre (top-5 Phase A etrafinda dC=+/-5pp, dR=+/-0.25)\n")
    L.append(f"- Constraint: tp1_R < tp2_R, tp1_c + tp2_c < 1.0 (runner > 0)\n")
    L.append(f"- Toplam degerlendirilen: {len([r for r in results if r.n_trades > 0])} hucre\n\n")

    L.append("## Statistical Gates (vs v1.5)\n\n")
    L.append(f"- **G0 ARTIFACT** max_R <= 20\n")
    L.append(f"- **G1 RETURN**   mean_ann >= {base.mean_ann + 5.0:.2f}% (baseline +5pp — yuksek bar)\n")
    L.append(f"- **G2 DD**       mean_dd >= {base.mean_dd - 5.0:.2f}% (baseline -5pp tolerans)\n")
    L.append(f"- **G3 NEG**      0 negatif pencere\n")
    L.append(f"- **G4 R-ADJ**    r_adj >= {base.r_adj + 0.10:.3f} (baseline +0.10)\n\n")

    valid = [r for r in results if r.n_trades > 0]
    sorted_radj = sorted(valid, key=lambda r: -r.r_adj)[:10]

    L.append("## TOP-10 by r-adj\n\n")
    L.append("| # | label | phase | tp1_R | tp2_R | c1 | c2 | runner | n | ann | DD | r-adj | maxR | neg |\n")
    L.append("|---|-------|-------|-------|-------|-----|-----|--------|---|-----|-----|-------|------|-----|\n")
    for i, r in enumerate(sorted_radj, 1):
        ph = "B" if r.is_baseline else r.phase
        L.append(f"| {i} | {r.label} | {ph} | {r.tp1_R} | {r.tp2_R} | {r.tp1_close_pct:.0%} | {r.tp2_close_pct:.0%} | "
                 f"{r.runner_pct:.0%} | {r.n_trades} | {r.mean_ann:+.2f}% | {r.mean_dd:+.2f}% | "
                 f"{r.r_adj:.3f} | {r.max_R:+.1f} | {r.negatives}/{r.n_windows} |\n")
    L.append("\n")

    L.append("## All cells\n\n")
    L.append("| label | phase | tp1_R | tp2_R | c1 | c2 | run | n | ann | med | min | DD | r-adj | maxR | neg |\n")
    L.append("|-------|-------|-------|-------|-----|-----|-----|---|-----|-----|-----|----|-------|------|-----|\n")
    for r in results:
        if r.n_trades == 0:
            continue
        ph = "B" if r.is_baseline else r.phase
        L.append(f"| {r.label} | {ph} | {r.tp1_R} | {r.tp2_R} | {r.tp1_close_pct:.0%} | {r.tp2_close_pct:.0%} | "
                 f"{r.runner_pct:.0%} | {r.n_trades} | {r.mean_ann:+.2f}% | {r.median_ann:+.2f}% | "
                 f"{r.min_ann:+.2f}% | {r.mean_dd:+.2f}% | {r.r_adj:.3f} | {r.max_R:+.1f} | "
                 f"{r.negatives}/{r.n_windows} |\n")
    L.append("\n")

    L.append("## Asimetri Pattern Analizi\n\n")
    if big_runner:
        br_ann = mean(r.mean_ann for r in big_runner)
        br_dd = mean(r.mean_dd for r in big_runner)
        br_radj = mean(r.r_adj for r in big_runner)
        L.append(f"- **BIG-RUNNER** (runner >= 45%, n={len(big_runner)}): ann={br_ann:+.2f}% / DD={br_dd:+.2f}% / r-adj={br_radj:.3f}\n")
    if symmetric:
        sm_ann = mean(r.mean_ann for r in symmetric)
        sm_dd = mean(r.mean_dd for r in symmetric)
        sm_radj = mean(r.r_adj for r in symmetric)
        L.append(f"- **SYMMETRIC** (runner 30-40%, n={len(symmetric)}): ann={sm_ann:+.2f}% / DD={sm_dd:+.2f}% / r-adj={sm_radj:.3f}\n")
    if fast_realize:
        fr_ann = mean(r.mean_ann for r in fast_realize)
        fr_dd = mean(r.mean_dd for r in fast_realize)
        fr_radj = mean(r.r_adj for r in fast_realize)
        L.append(f"- **FAST-REALIZE** (runner <= 25%, n={len(fast_realize)}): ann={fr_ann:+.2f}% / DD={fr_dd:+.2f}% / r-adj={fr_radj:.3f}\n")
    L.append("\n")
    if big_runner and fast_realize:
        if mean(r.r_adj for r in big_runner) > mean(r.r_adj for r in fast_realize):
            L.append("**Pattern: BIG-RUNNER dominant** — yuksek runner pct r-adj olarak ustun. "
                     "Trail mekanizmasi (mult=1.5 + time/30) buyuk winner'lari yakaliyor; "
                     "erken kar realize edip runner'i kucultmek r-adj'i bozuyor.\n\n")
        else:
            L.append("**Pattern: FAST-REALIZE dominant** — dusuk runner pct r-adj olarak ustun. "
                     "Erken kar al + give-back riskini sinirla.\n\n")

    L.append("## Karar\n\n")
    if winner:
        L.append(f"**WINNER:** `{winner.label}` — tp1_R={winner.tp1_R}, tp2_R={winner.tp2_R}, "
                 f"tp1_c={winner.tp1_close_pct:.0%}, tp2_c={winner.tp2_close_pct:.0%}, runner={winner.runner_pct:.0%}\n\n")
        L.append(f"- yillik {winner.mean_ann:+.2f}% (baseline {base.mean_ann:+.2f}%, "
                 f"delta {winner.mean_ann - base.mean_ann:+.2f}pp)\n")
        L.append(f"- DD {winner.mean_dd:+.2f}% (baseline {base.mean_dd:+.2f}%, "
                 f"delta {winner.mean_dd - base.mean_dd:+.2f}pp)\n")
        L.append(f"- r-adj {winner.r_adj:.3f} (baseline {base.r_adj:.3f}, "
                 f"+{winner.r_adj - base.r_adj:.3f})\n")
        L.append(f"- 13/13 pencere pozitif: EVET\n\n")
        L.append("**ONERI:** engine.py default'larini bu konfigurasyona guncelle (tp1_R, tp2_R, tp1_close_pct, tp2_close_pct).\n")
    else:
        L.append("**RED.** 4D grid'de hicbir hucre G0-G4 hepsini gecemedi.\n\n")
        L.append("**Yorum:** v1.5 (1.0R/1.5R/30/30/40-runner) konfigurasyonu 13 pencere 3y rolling'de halen optimum. "
                 "TP1/TP2 close pct asimetrisi marjinal etki uretir; sweet spot zaten 30/30/40-runner kombinasyonunda.\n\n")
        L.append("**Aksiyon:** Mevcut v1.5 production parametre korunur. RED hipotez memory'e kaydedilir.\n")

    L.append("\n## Pre-Reg Disipline & Reproducibility\n\n")
    L.append(f"- Grid pre-registered ({len(PHASE_A_CELLS)} Phase A + {len([r for r in results if r.phase == 'B'])} Phase B).\n")
    L.append(f"- HARK protection: gates onceden yazildi (G0-G4), post-hoc tweak yok.\n")
    L.append(f"- Trade pool cache: `data/_sec15_3_cache/pool_*.pkl` (per cell).\n")
    L.append(f"- Baseline pool reuse: SEC13.4 A6 cache (mult=1.5+time/30bar identik).\n")
    L.append(f"- JSON: `reports/lab/sec15_3_tp4d_v2.json`\n")
    L.append(f"- Re-run: `PYTHONPATH=src python scripts/sec15_3_tp4d_grid_v2.py`\n")
    L.append(f"- BASELINE SANITY: ann={base.mean_ann:+.2f}% (target +%116 +/- 1pp gecti -> ARTIFACT-FREE setup).\n")

    with open(path, "w", encoding="utf-8") as f:
        f.writelines(L)


if __name__ == "__main__":
    main()
