"""SEC12.B — Multi-Target TP 4D DEEP GRID.

Hipotez:
  Mevcut sec11b sweep DARDI: sadece (tp1_R, tp2_R) sweep edildi, close_pct sabit %30/%30.
  4D grid (tp1_R, tp2_R, tp1_close_pct, tp2_close_pct) ile asimetrik partial fraction
  belki ek alpha üretebilir:
   - tp1'de %50 kapat -> erken kar al, runner küçük
   - tp1'de %20 kapat -> daha çok runner için bırak
   - tp2'de %0 (manuel ekstrem: tp2_close_pct=0, tp2 yok) -> 1R partial + runner trail
   - tp2'de %50 -> daha az runner

Smart sampling (zamanlı):
  PHASE 1: BASELINE (v1.2: 1.0R/1.5R/30/30) = referans
  PHASE 2: tp1_close x tp2_close 4x4 sweep at v1.2 R-points (1.0/1.5) = 16 hücre
  PHASE 3: 2 EKSTREM PROFIL (Aggressive Runner + Conservative Book)
  PHASE 4: Phase 2'de en iyi 4-5 close-config etrafında R-sweep (alt grid 8-12 hücre)

Statistical gates (her hücre için):
  - Yıllık return baseline (+%51.2) üstüne min +%2pp (yüksek bar — sweep DAR olduğundan)
  - DD baseline (-%34.2) tolerans +%5pp (yani DD >= -39.2% kabul)
  - 13 pencere 0 negatif
  - r-adj iyileşme >= +0.05

Methodology:
  - 11 sym × TOP_11 (TOP_10 + fvg_fill_reversal) = trade pool gen
  - Engine: runner_trail_mult=2.0 (v1.2 production sabit)
  - 13 pencere 3y rolling, BALANCED+halt+F&G+funding+monthly_dd=0.08, production_replay canonical
  - Constraint: tp1_R < tp2_R, tp1_close_pct + tp2_close_pct < 1.0 (runner > 0)

HARK protection: pre-registered grid, "en iyi 1 pencere" cherry-pick yasak.
Mean across 13 windows + zero negative gate.

Output: reports/lab/sec12b_tp4d_grid.md
"""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path
from statistics import mean, median

os.environ["PA_LOG_QUIET"] = "1"
import warnings
warnings.filterwarnings("ignore")

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from price_action.backtest.engine import BacktestEngine
from price_action.backtest.lab import (
    ProductionConfig,
    production_replay,
    _lazy_build_funding_filters,
)
from price_action.backtest.regime import compute_btc_capitulation_halt
from price_action.signals.filters import volume_zscore
from scripts.run_real_backtest import _load_symbol_ohlcv
from scripts.v09_optimize_top10 import SYMBOLS_11, TOP_10
from scripts.v097_balanced_optimization import DROP_PAIRS, build_fng_short_skip

# v1.2 portfolio: TOP_10 + fvg_fill_reversal
TOP_11 = TOP_10 + [("fvg_fill_reversal", "FVGFillReversalStrategy")]


# =====================================================================
# Engine-parametrize trade gather (multi-target params override)
# =====================================================================

def _gather_with_engine_params(
    module_name: str,
    class_name: str,
    *,
    runner_trail_mult: float = 2.0,  # v1.2 production
    tp1_R: float = 1.0,
    tp2_R: float = 1.5,
    tp1_close_pct: float = 0.30,
    tp2_close_pct: float = 0.30,
) -> list[dict]:
    """Engine 4D-parametrize trade pool gen — v1.2 stack (trail=2.0, FVG eklendi)."""
    try:
        mod = __import__(
            f"price_action.strategies.{module_name}",
            fromlist=[class_name, "_default_manifest"],
        )
        cls = getattr(mod, class_name)
        manifest_fn = getattr(mod, "_default_manifest", None)
        if not manifest_fn:
            return []
        s = cls(manifest_fn())
    except Exception as e:
        print(f"  [WARN] {module_name}: {e}")
        return []

    out: list[dict] = []
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
                risk_officer=None,
                store_load=None,
                runner_trail_mult=runner_trail_mult,
                tp1_R=tp1_R,
                tp2_R=tp2_R,
                tp1_close_pct=tp1_close_pct,
                tp2_close_pct=tp2_close_pct,
            )
            r = e.run(
                s,
                [sym],
                start=df["ts"].iloc[0].to_pydatetime(),
                end=df["ts"].iloc[-1].to_pydatetime(),
                timeframe="1d",
                initial_capital=10_000.0,
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
                    "entry_ts": ts_e,
                    "exit_ts": ts_x,
                    "entry_price": float(t["entry_price"]),
                    "initial_sl": float(t["initial_sl"]),
                    "R": float(t["realized_r_multiple"]),
                    "symbol": sym,
                    "side": str(t["side"]).lower(),
                    "conf": conf,
                    "strategy": module_name,
                    "vol_z": vz,
                })
        except Exception as e:
            print(f"  [WARN] {module_name} on {sym}: {e}")
            continue
    return out


# =====================================================================
# Walk-forward 13 pencere
# =====================================================================

@dataclass
class GridResult:
    label: str
    tp1_R: float
    tp2_R: float
    tp1_close_pct: float
    tp2_close_pct: float
    runner_pct: float
    n_trades_pool: int
    annual_mean: float
    annual_median: float
    annual_min: float
    annual_max: float
    dd_mean: float
    dd_worst: float
    r_adj: float
    n_negative: int
    n_windows: int

    def passes_gates(self, baseline_ann: float, baseline_dd: float, baseline_radj: float) -> tuple[bool, list[str]]:
        reasons: list[str] = []
        if self.annual_mean < baseline_ann + 2.0:
            reasons.append(f"yillik {self.annual_mean:+.2f}% < baseline+2pp ({baseline_ann + 2.0:+.2f}%)")
        dd_floor = baseline_dd - 5.0
        if self.dd_mean < dd_floor:
            reasons.append(f"DD {self.dd_mean:+.2f}% < tolerans ({dd_floor:+.2f}%)")
        if self.n_negative > 0:
            reasons.append(f"negatif pencere = {self.n_negative} (>0)")
        if self.r_adj < baseline_radj + 0.05:
            reasons.append(f"r-adj {self.r_adj:.3f} < baseline+0.05 ({baseline_radj + 0.05:.3f})")
        return len(reasons) == 0, reasons


def run_walkforward(trades: list[dict], cfg: ProductionConfig, windows: list[tuple]):
    anns: list[float] = []
    dds: list[float] = []
    for ws, we in windows:
        ww_t = [t for t in trades if ws <= t["entry_ts"] < we]
        r = production_replay(ww_t, cfg)
        if r is None or r.trades == 0:
            continue
        anns.append(r.annualized(3.0) * 100)
        dds.append(r.max_drawdown * 100)
    if not anns:
        return 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0, 0, 0.0
    ann_mean = mean(anns)
    ann_median = median(anns)
    ann_min = min(anns)
    ann_max = max(anns)
    dd_mean = mean(dds)
    dd_worst = min(dds)
    n_neg = sum(1 for a in anns if a < 0)
    n_win = len(anns)
    r_adj = ann_mean / abs(dd_mean) if dd_mean != 0 else 0.0
    return ann_mean, ann_median, ann_min, ann_max, dd_mean, dd_worst, n_neg, n_win, r_adj


def gen_pool(strats, *, runner_trail_mult, tp1_R, tp2_R, tp1_close_pct, tp2_close_pct):
    pool: list[dict] = []
    for m, c in strats:
        pool.extend(
            _gather_with_engine_params(
                m, c,
                runner_trail_mult=runner_trail_mult,
                tp1_R=tp1_R, tp2_R=tp2_R,
                tp1_close_pct=tp1_close_pct, tp2_close_pct=tp2_close_pct,
            )
        )
    pool.sort(key=lambda x: x["entry_ts"])
    return pool


def eval_cell(label, *, tp1_R, tp2_R, tp1_close_pct, tp2_close_pct,
              cfg, windows, runner_trail_mult=2.0, log=True) -> GridResult:
    pool = gen_pool(TOP_11, runner_trail_mult=runner_trail_mult,
                    tp1_R=tp1_R, tp2_R=tp2_R,
                    tp1_close_pct=tp1_close_pct, tp2_close_pct=tp2_close_pct)
    if not pool:
        if log:
            print(f"  {label:<28} POOL EMPTY")
        return GridResult(label, tp1_R, tp2_R, tp1_close_pct, tp2_close_pct,
                          1.0 - tp1_close_pct - tp2_close_pct, 0,
                          0, 0, 0, 0, 0, 0, 0, 0, 0)
    ann_m, ann_med, ann_min, ann_max, dd_m, dd_w, n_neg, n_win, r_adj = run_walkforward(pool, cfg, windows)
    runner_pct = 1.0 - tp1_close_pct - tp2_close_pct
    gr = GridResult(label, tp1_R, tp2_R, tp1_close_pct, tp2_close_pct, runner_pct,
                    len(pool), ann_m, ann_med, ann_min, ann_max, dd_m, dd_w, r_adj, n_neg, n_win)
    if log:
        print(f"  {label:<28} {len(pool):>6} {ann_m:>+7.2f}% {ann_med:>+6.2f}% {ann_min:>+6.2f}% "
              f"{dd_m:>+7.2f}% {dd_w:>+8.2f}% {r_adj:>5.3f} {n_neg:>2}/{n_win:>2}")
    return gr


# =====================================================================
# Main: smart sampling 4D sweep
# =====================================================================

def main() -> None:
    print("=" * 120)
    print("SEC12.B — MULTI-TARGET TP 4D DEEP GRID (v1.2 BALANCED+FVG+trail=2.0+tp2_R=1.5 baseline)")
    print("=" * 120)

    # --- Config v1.2 (sec11_final_stack — FULL STACK A+B+E) ---
    print("\n[1/5] Filter calendars + v1.2 cfg setup...")
    halt_cal = compute_btc_capitulation_halt()
    fund_long, fund_short = _lazy_build_funding_filters({
        "funding_filter_enabled": True,
        "funding_aggregation_mode": "00:00_only",
    })
    fng_short_20 = build_fng_short_skip(20)
    combined_short_skip = {**dict(fund_short or {}), **dict(fng_short_20)}
    print(f"  halt: {sum(1 for v in halt_cal.values() if v)}/{len(halt_cal)} gun")
    print(f"  funding short-skip: {len(fund_short or {})} gun")
    print(f"  F&G short-skip (<=20): {len(fng_short_20)} gun")
    print(f"  combined short-skip: {len(combined_short_skip)} gun")

    base_bal = ProductionConfig.from_yaml("configs/risk_balanced.yaml")
    cfg = base_bal.with_overrides(
        btc_halt_calendar=halt_cal,
        alt_data_skip_long=fund_long,
        alt_data_skip_short=combined_short_skip,
        drop_pairs=DROP_PAIRS,
        monthly_dd=0.08,
    )
    print(f"  cfg risk_pct={cfg.risk_pct}, monthly_dd={cfg.monthly_dd}, max_concurrent={cfg.max_concurrent}")

    RUNNER_TRAIL = 2.0  # v1.2 production sabit (sec11.A + B + E full stack)

    # --- Generate baseline v1.2 pool first to establish rolling windows ---
    print("\n[2/5] BASELINE v1.2 pool gen (1.0R/1.5R/30/30) — ortak rolling pencere...")
    baseline_pool = gen_pool(TOP_11, runner_trail_mult=RUNNER_TRAIL,
                             tp1_R=1.0, tp2_R=1.5, tp1_close_pct=0.30, tp2_close_pct=0.30)
    if not baseline_pool:
        print("HATA: baseline pool bos!")
        return
    print(f"  Baseline pool: {len(baseline_pool)} trade")

    start = baseline_pool[0]["entry_ts"]
    end = baseline_pool[-1]["exit_ts"]
    windows: list[tuple] = []
    cur = start
    while cur + pd.Timedelta(days=3 * 365) <= end:
        windows.append((cur, cur + pd.Timedelta(days=3 * 365)))
        cur += pd.Timedelta(days=60)
    print(f"  Pencere sayisi (3y rolling, 60d step): {len(windows)}")

    print("\n  Header:  cell                       n_pool  ann_mean ann_med ann_min  DD_mean  DD_worst r-adj neg/n")
    print("  " + "-" * 110)
    base_grid = eval_cell("BASELINE_v1.2", tp1_R=1.0, tp2_R=1.5,
                          tp1_close_pct=0.30, tp2_close_pct=0.30,
                          cfg=cfg, windows=windows, runner_trail_mult=RUNNER_TRAIL)
    base_ann, base_dd, base_radj = base_grid.annual_mean, base_grid.dd_mean, base_grid.r_adj

    all_results: list[GridResult] = [base_grid]

    # =========================================================================
    # PHASE 2: tp1_close × tp2_close 4×4 grid at v1.2 R-points (1.0R / 1.5R)
    # =========================================================================
    print("\n[3/5] PHASE 2 — close_pct 4x4 sweep at v1.2 R-points (1.0R / 1.5R)")
    print(f"   tp1_close ∈ {{0.20, 0.30(B), 0.40, 0.50}}, tp2_close ∈ {{0.20, 0.30(B), 0.40, 0.50}}")
    print(f"   constraint: tp1+tp2 < 1.0 (runner>0)")
    p2_grid: list[GridResult] = []
    p2_close_vals = [0.20, 0.30, 0.40, 0.50]
    for tp1c in p2_close_vals:
        for tp2c in p2_close_vals:
            if tp1c + tp2c >= 1.0:
                continue
            # Skip baseline (already done)
            if abs(tp1c - 0.30) < 1e-6 and abs(tp2c - 0.30) < 1e-6:
                continue
            label = f"P2 1.0/1.5/{int(tp1c*100)}/{int(tp2c*100)}"
            gr = eval_cell(label, tp1_R=1.0, tp2_R=1.5,
                           tp1_close_pct=tp1c, tp2_close_pct=tp2c,
                           cfg=cfg, windows=windows, runner_trail_mult=RUNNER_TRAIL)
            p2_grid.append(gr)
    all_results.extend(p2_grid)

    # =========================================================================
    # PHASE 3: 2 EKSTREM PROFIL
    # =========================================================================
    print("\n[4/5] PHASE 3 — 2 EKSTREM PROFIL")
    print("   AGGRESSIVE_RUNNER: tp1=0.5R 50% + tp2 yok (tp2_close=0) + runner 50%")
    print("   CONSERVATIVE_BOOK: tp1=1.0R 50% + tp2=1.5R 30% + runner 20%")
    p3_grid: list[GridResult] = []

    # Aggressive runner: tp2 yok demek pratikte tp2_close_pct=0.0 -> qty2=0, partial #2 hiç tetiklenmez
    # tp2_R irrelevant olur (qty2=0 ise hiç fill yok). Yine de sembolik tp2_R=2.0 verelim, etkisi yok.
    gr_agr = eval_cell("P3 AGGRESSIVE_RUNNER", tp1_R=0.5, tp2_R=2.0,
                       tp1_close_pct=0.50, tp2_close_pct=0.0,
                       cfg=cfg, windows=windows, runner_trail_mult=RUNNER_TRAIL)
    p3_grid.append(gr_agr)

    gr_con = eval_cell("P3 CONSERVATIVE_BOOK", tp1_R=1.0, tp2_R=1.5,
                       tp1_close_pct=0.50, tp2_close_pct=0.30,
                       cfg=cfg, windows=windows, runner_trail_mult=RUNNER_TRAIL)
    # Note: P3 CONSERV cell == P2 50/30 (already done) — but record duplicate label for asymmetric analysis
    # Skip if exact dup already exists
    dup = any(abs(g.tp1_close_pct - 0.50) < 1e-6 and abs(g.tp2_close_pct - 0.30) < 1e-6
              and abs(g.tp1_R - 1.0) < 1e-6 and abs(g.tp2_R - 1.5) < 1e-6
              for g in p2_grid)
    if not dup:
        p3_grid.append(gr_con)
    all_results.extend(p3_grid)

    # =========================================================================
    # PHASE 4: top-region fine grid — Phase 2 best-4 etrafinda R sweep
    # =========================================================================
    print("\n[5/5] PHASE 4 — top-region R-sweep (Phase 2 best-4 close-config etrafinda)")
    # Pre-registered R sweep set (HARK protection: sabit liste, en iyi pencere cherry-pick yok)
    p2_sorted = sorted(p2_grid, key=lambda g: g.r_adj, reverse=True)[:4]
    print(f"   Top-4 close configs (by r-adj): "
          f"{[(g.tp1_close_pct, g.tp2_close_pct, round(g.r_adj, 3)) for g in p2_sorted]}")

    # R-variant grid pre-reg: her top close config için 3 ek R sweep (toplam ~12 hücre)
    r_variants = [
        (0.75, 1.5),  # daha yakın tp1
        (1.0, 1.25),  # daha sıkı tp2
        (1.25, 1.75), # daha geniş hedef
    ]
    p4_grid: list[GridResult] = []
    for top_g in p2_sorted:
        tp1c, tp2c = top_g.tp1_close_pct, top_g.tp2_close_pct
        for tp1R, tp2R in r_variants:
            if tp1R >= tp2R:
                continue
            label = f"P4 {tp1R}/{tp2R}/{int(tp1c*100)}/{int(tp2c*100)}"
            gr = eval_cell(label, tp1_R=tp1R, tp2_R=tp2R,
                           tp1_close_pct=tp1c, tp2_close_pct=tp2c,
                           cfg=cfg, windows=windows, runner_trail_mult=RUNNER_TRAIL)
            p4_grid.append(gr)
    all_results.extend(p4_grid)

    # =========================================================================
    # STATISTICAL GATES + INSIGHT
    # =========================================================================
    print("\n--- STATISTICAL GATES (vs v1.2 BASELINE) ---")
    print(f"  Baseline: ann={base_ann:+.2f}%, DD={base_dd:+.2f}%, r-adj={base_radj:.3f}")
    print(f"  PASS: ann>=+{base_ann+2.0:.2f}% AND DD>={base_dd-5.0:+.2f}% AND r-adj>={base_radj+0.05:.3f} AND neg=0\n")

    passed: list[GridResult] = []
    for gr in all_results:
        if gr.label == "BASELINE_v1.2":
            continue
        if gr.n_trades_pool == 0:
            continue
        ok, reasons = gr.passes_gates(base_ann, base_dd, base_radj)
        tag = "PASS" if ok else "FAIL"
        rsn = "; ".join(reasons)[:90] if reasons else "-"
        print(f"  {gr.label:<28} {tag:<5} {rsn}")
        if ok:
            passed.append(gr)

    # Top-10 by r-adj
    valid = [g for g in all_results if g.n_trades_pool > 0]
    sorted_radj = sorted(valid, key=lambda g: g.r_adj, reverse=True)[:10]
    print("\n--- TOP-10 BY r-adj ---")
    for i, g in enumerate(sorted_radj, 1):
        runner = 1.0 - g.tp1_close_pct - g.tp2_close_pct
        print(f"  #{i:2d} {g.label:<28} ann={g.annual_mean:+.2f}% DD={g.dd_mean:+.2f}% "
              f"r-adj={g.r_adj:.3f} runner={runner:.0%} neg={g.n_negative}")

    # Insight: big-runner vs fast-realize pattern
    print("\n--- INSIGHT: PATTERN ANALYSIS ---")
    # Big-runner: runner_pct >= 0.50
    big_runner = [g for g in valid if (1.0 - g.tp1_close_pct - g.tp2_close_pct) >= 0.50 and g.label != "BASELINE_v1.2"]
    fast_realize = [g for g in valid if (1.0 - g.tp1_close_pct - g.tp2_close_pct) <= 0.30 and g.label != "BASELINE_v1.2"]
    if big_runner:
        br_ann = mean(g.annual_mean for g in big_runner)
        br_dd = mean(g.dd_mean for g in big_runner)
        br_radj = mean(g.r_adj for g in big_runner)
        print(f"  BIG-RUNNER (runner>=50%, n={len(big_runner)}): ann_avg={br_ann:+.2f}% DD_avg={br_dd:+.2f}% r-adj_avg={br_radj:.3f}")
    if fast_realize:
        fr_ann = mean(g.annual_mean for g in fast_realize)
        fr_dd = mean(g.dd_mean for g in fast_realize)
        fr_radj = mean(g.r_adj for g in fast_realize)
        print(f"  FAST-REALIZE (runner<=30%, n={len(fast_realize)}): ann_avg={fr_ann:+.2f}% DD_avg={fr_dd:+.2f}% r-adj_avg={fr_radj:.3f}")

    # Final winner
    print("\n--- FINAL WINNER (PASS only, sorted by r-adj desc) ---")
    if passed:
        passed.sort(key=lambda g: g.r_adj, reverse=True)
        best = passed[0]
        runner = 1.0 - best.tp1_close_pct - best.tp2_close_pct
        print(f"  WINNER: tp1_R={best.tp1_R}, tp2_R={best.tp2_R}, "
              f"tp1_close={best.tp1_close_pct:.0%}, tp2_close={best.tp2_close_pct:.0%}, runner={runner:.0%}")
        print(f"    yillik {best.annual_mean:+.2f}% (vs baseline {base_ann:+.2f}, +{best.annual_mean - base_ann:+.2f}pp)")
        print(f"    DD     {best.dd_mean:+.2f}% (vs baseline {base_dd:+.2f}, +{best.dd_mean - base_dd:+.2f}pp)")
        print(f"    r-adj  {best.r_adj:.3f} (vs baseline {base_radj:.3f}, +{best.r_adj - base_radj:.3f})")
    else:
        print("  HIC PASS YOK — v1.2 baseline (1.0R/1.5R/30/30) optimum kalir.")

    # --- Markdown report ---
    out_md = ROOT / "reports" / "lab" / "sec12b_tp4d_grid.md"
    out_md.parent.mkdir(parents=True, exist_ok=True)
    write_report(out_md, base_grid, all_results, passed, big_runner, fast_realize)
    print(f"\nReport: {out_md}")


def write_report(path: Path, base: GridResult, results: list[GridResult],
                 passed: list[GridResult],
                 big_runner: list[GridResult],
                 fast_realize: list[GridResult]) -> None:
    lines: list[str] = []
    lines.append("# SEC12.B — Multi-Target TP 4D DEEP Grid")
    lines.append("")
    lines.append("**Tarih:** 2026-05-13")
    lines.append("**Branch:** main (v1.2.0 baseline — BALANCED+FVG+trail=2.0+tp2_R=1.5+monthly_dd=0.08)")
    lines.append("**Methodology:** 11 sym × TOP_11 (TOP_10 + fvg_fill_reversal) × 13 pencere 3y rolling")
    lines.append("")
    lines.append("## TL;DR")
    lines.append("")

    valid = [g for g in results if g.n_trades_pool > 0]
    sorted_radj = sorted(valid, key=lambda g: g.r_adj, reverse=True)[:10]

    if passed:
        passed.sort(key=lambda g: g.r_adj, reverse=True)
        best = passed[0]
        runner = 1.0 - best.tp1_close_pct - best.tp2_close_pct
        lines.append(f"**WIN:** `{best.label}` — tp1_R={best.tp1_R}, tp2_R={best.tp2_R}, "
                     f"tp1_close={best.tp1_close_pct:.0%}, tp2_close={best.tp2_close_pct:.0%}, runner={runner:.0%}")
        lines.append(f"- yillik {best.annual_mean:+.2f}% (baseline {base.annual_mean:+.2f}%, **{best.annual_mean - base.annual_mean:+.2f}pp**)")
        lines.append(f"- DD {best.dd_mean:+.2f}% (baseline {base.dd_mean:+.2f}%, {best.dd_mean - base.dd_mean:+.2f}pp)")
        lines.append(f"- r-adj {best.r_adj:.3f} (baseline {base.r_adj:.3f}, {best.r_adj - base.r_adj:+.3f})")
        lines.append(f"- 13 pencere negatif: {best.n_negative}")
    else:
        lines.append("**RED:** Hic bir hücre 4 gate'i (ann+DD+r-adj+neg=0) gecemedi. v1.2 baseline (1.0R/1.5R/30/30) optimum kalir.")
    lines.append("")
    lines.append("**Sec11.B sweep dar yere parmak basildi:** Sadece tp1_R x tp2_R sweep edilmisti, close_pct sabit %30/%30. "
                 "4D'de tp1_close_pct ve tp2_close_pct'nin partial-fraction etkisi izole edildi (16 close × R kombinasyonu + 2 ekstrem profil + Phase 4 fine).")
    lines.append("")

    lines.append("## Hipotez")
    lines.append("")
    lines.append("v1.2'de PROMOTE edilen FULL STACK (sec11) sonrasi multi-target TP **2D sweep darmis**:")
    lines.append("- Sec11.B sadece (tp1_R, tp2_R) sweep etti — close_pct sabit %30/%30")
    lines.append("- Asimetrik partial fraction tek basina ek alpha uretebilir mi?")
    lines.append("  - tp1'de %50 kapat -> erken kar al, runner kucuk")
    lines.append("  - tp1'de %20 kapat -> daha cok runner")
    lines.append("  - tp2'de %0 (tp2 yok) -> 1R partial + runner trail tek")
    lines.append("  - tp2'de %50 -> daha az runner")
    lines.append("")
    lines.append("## Smart sampling")
    lines.append("")
    lines.append("Toplam ~80-100 hücreli ham 4D grid yerine pre-registered 4-fazli akilli sampling:")
    lines.append("- **PHASE 1**: BASELINE v1.2 (1.0R/1.5R/30/30)")
    lines.append("- **PHASE 2**: close_pct 4x4 grid at R=(1.0/1.5) — runner-fraksiyon marjinal etki izolasyonu")
    lines.append("- **PHASE 3**: 2 EKSTREM PROFIL (Aggressive Runner: 0.5R/50% no-tp2 + runner 50%; Conservative Book: 50/30/runner 20%)")
    lines.append("- **PHASE 4**: top-4 close-config etrafinda R-variant ek sweep (3 R-pair × 4 close = 12 hücre)")
    lines.append("")
    lines.append(f"Toplam degerlendirilen hücre: {len(valid)}")
    lines.append("")
    lines.append("## Statistical gates")
    lines.append("")
    lines.append(f"- Yillik return >= baseline + 2pp ({base.annual_mean + 2.0:+.2f}%) — yuksek bar (sec11.B 1pp idi, 4D'de daha disiplinli)")
    lines.append(f"- DD >= baseline - 5pp tolerans ({base.dd_mean - 5.0:+.2f}%)")
    lines.append(f"- r-adj >= baseline + 0.05 ({base.r_adj + 0.05:.3f})")
    lines.append("- 13 pencere 0 negatif")
    lines.append("")

    # --- TOP-10 ---
    lines.append("## TOP-10 by r-adj")
    lines.append("")
    lines.append("| # | label | tp1_R | tp2_R | tp1_c | tp2_c | runner | n_pool | ann_mean | DD | r-adj | neg/n |")
    lines.append("|---|---|---|---|---|---|---|---|---|---|---|---|")
    for i, g in enumerate(sorted_radj, 1):
        runner = 1.0 - g.tp1_close_pct - g.tp2_close_pct
        lines.append(
            f"| {i} | {g.label} | {g.tp1_R} | {g.tp2_R} | {g.tp1_close_pct:.0%} | {g.tp2_close_pct:.0%} | "
            f"{runner:.0%} | {g.n_trades_pool} | {g.annual_mean:+.2f}% | {g.dd_mean:+.2f}% | {g.r_adj:.3f} | "
            f"{g.n_negative}/{g.n_windows} |"
        )
    lines.append("")

    # --- All Results ---
    lines.append("## Tum hücreler")
    lines.append("")
    lines.append("| label | tp1_R | tp2_R | tp1_c | tp2_c | runner | n_pool | ann_mean | ann_med | ann_min | DD_mean | DD_worst | r-adj | neg/n |")
    lines.append("|---|---|---|---|---|---|---|---|---|---|---|---|---|---|")
    for g in results:
        if g.n_trades_pool == 0:
            continue
        runner = 1.0 - g.tp1_close_pct - g.tp2_close_pct
        lines.append(
            f"| {g.label} | {g.tp1_R} | {g.tp2_R} | {g.tp1_close_pct:.0%} | {g.tp2_close_pct:.0%} | "
            f"{runner:.0%} | {g.n_trades_pool} | {g.annual_mean:+.2f}% | {g.annual_median:+.2f}% | "
            f"{g.annual_min:+.2f}% | {g.dd_mean:+.2f}% | {g.dd_worst:+.2f}% | {g.r_adj:.3f} | {g.n_negative}/{g.n_windows} |"
        )
    lines.append("")

    # --- INSIGHT ---
    lines.append("## INSIGHT — Big-Runner vs Fast-Realize")
    lines.append("")
    if big_runner:
        br_ann = mean(g.annual_mean for g in big_runner)
        br_dd = mean(g.dd_mean for g in big_runner)
        br_radj = mean(g.r_adj for g in big_runner)
        lines.append(f"**BIG-RUNNER** (runner_pct >= 50%, n={len(big_runner)}): "
                     f"ann_avg={br_ann:+.2f}% / DD_avg={br_dd:+.2f}% / r-adj_avg={br_radj:.3f}")
    if fast_realize:
        fr_ann = mean(g.annual_mean for g in fast_realize)
        fr_dd = mean(g.dd_mean for g in fast_realize)
        fr_radj = mean(g.r_adj for g in fast_realize)
        lines.append(f"**FAST-REALIZE** (runner_pct <= 30%, n={len(fast_realize)}): "
                     f"ann_avg={fr_ann:+.2f}% / DD_avg={fr_dd:+.2f}% / r-adj_avg={fr_radj:.3f}")
    lines.append("")
    if big_runner and fast_realize:
        if br_radj > fr_radj:
            lines.append("**Pattern: BIG-RUNNER dominant** — düşük close fraction (yüksek runner pct) r-adj olarak üstün. "
                         "Trail-ATR mekanizması büyük winner'ları yakalıyor; erken kar realize edip runner kısmını "
                         "küçültmek r-adj'i bozuyor.")
        else:
            lines.append("**Pattern: FAST-REALIZE dominant** — yüksek close fraction (düşük runner) r-adj olarak üstün. "
                         "Erken kar al + give-back riskini sınırla, runner'ı küçük tut. v1.2'nin %40 runner'ı "
                         "muhtemelen yüksek; %20-30'a indirmek faydali olabilir.")
    lines.append("")

    # --- GATES ---
    lines.append("## Gate evaluation")
    lines.append("")
    lines.append("| label | PASS | reasons |")
    lines.append("|---|---|---|")
    for g in results:
        if g.label == "BASELINE_v1.2":
            lines.append(f"| {g.label} | (ref) | n/a |")
            continue
        if g.n_trades_pool == 0:
            lines.append(f"| {g.label} | FAIL | POOL EMPTY |")
            continue
        ok, reasons = g.passes_gates(base.annual_mean, base.dd_mean, base.r_adj)
        tag = "PASS" if ok else "FAIL"
        rsn = "; ".join(reasons) if reasons else "-"
        lines.append(f"| {g.label} | {tag} | {rsn} |")
    lines.append("")

    # --- KARAR ---
    lines.append("## Karar")
    lines.append("")
    if passed:
        passed.sort(key=lambda g: g.r_adj, reverse=True)
        best = passed[0]
        runner = 1.0 - best.tp1_close_pct - best.tp2_close_pct
        lines.append(f"**WINNER:** `{best.label}` — tp1_R={best.tp1_R}, tp2_R={best.tp2_R}, "
                     f"tp1_close_pct={best.tp1_close_pct:.0%}, tp2_close_pct={best.tp2_close_pct:.0%}, runner={runner:.0%}")
        lines.append("")
        lines.append(f"- Yillik: {best.annual_mean:+.2f}% (baseline {base.annual_mean:+.2f}%, delta {best.annual_mean - base.annual_mean:+.2f}pp)")
        lines.append(f"- DD: {best.dd_mean:+.2f}% (baseline {base.dd_mean:+.2f}%, delta {best.dd_mean - base.dd_mean:+.2f}pp)")
        lines.append(f"- r-adj: {best.r_adj:.3f} (baseline {base.r_adj:.3f}, delta {best.r_adj - base.r_adj:+.3f})")
        lines.append(f"- 13 pencere negatif: {best.n_negative}")
        lines.append("")
        lines.append("**Aksiyon:** `configs/risk_balanced.yaml`'da `take_profit.partial_close_at_R`, `take_profit.primary_R`, "
                     "ve close fraksiyonlarini guncelle. Engine default'larini yeni v1.3 stack'ine tasi.")
    else:
        lines.append("**RED.** 4D grid'de hiç bir hücre 4 gate'i (ann + DD + r-adj + neg=0) gecemedi.")
        lines.append("")
        lines.append("Yapisal yorum: v1.2'nin (1.0R / 1.5R / 30/30/40-runner) konfigurasyonu 13 pencere 3y rolling'de halen optimum.")
        lines.append("4D'de partial fraction degisikligi bekleneni vermedi — close_pct +/-10pp 'daki sapmalar marjinal etki uretti, "
                     "yeterli alpha yok.")
        lines.append("")
        lines.append("**Aksiyon:** Mevcut v1.2 production parametre korunur. Bu sprint RED hipotez olarak memory'e kaydedilir. "
                     "Sonraki adim: confluence-tier sizing (CONF-based) veya symbol-aware close_pct (per-sym tuning).")
    lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    main()
