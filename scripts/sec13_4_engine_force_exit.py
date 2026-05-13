"""SEC13.4 — Engine Force-Exit ile mult=2.0 Production-Safe Trailing.

PRE-REGISTERED HIPOTEZ:
  SEC11.A grid'inde runner_trail_mult=2.0 ATR (cap=5R altinda) +%45.4/yil real edge
  uretti, fakat raw R=967 fantasy artifact backtest sonuna kadar runner tasidigindan
  gercek edge gizlendi. Engine'e runner force-exit (time / ema_cross / combined)
  eklenirse mult=2.0 production-safe olabilir.

GRID (pre-registered):
  baseline       : mult=1.0 + force_exit=atr_only            (v1.3 baseline kontrol)
  A1             : mult=2.0 + force_exit=atr_only            (sec11a fantasy ref)
  A2_t20         : mult=2.0 + time_exit=20bar
  A2_t30         : mult=2.0 + time_exit=30bar
  A2_t50         : mult=2.0 + time_exit=50bar
  A3_ema         : mult=2.0 + ema_cross
  A4_comb_t30    : mult=2.0 + combined (time=30 AND ema_cross) [en gevsek]
  A5_either_t30  : mult=2.0 + either   (time=30 OR  ema_cross) [en siki]
  A6_mid         : mult=1.5 + time_exit=30bar                 (ortayol)

V1.3 BASELINE (production):
  TOP_11, tp1_R=1.0, tp2_R=1.5, monthly_dd=0.06, halt_days=21
  yillik +%60.2 / DD -%33.4 / r-adj 1.802 / 13/13 pencere pozitif

GATES (pre-registered, HARK protection):
  G0 ARTIFACT  max_R(any single trade) <= 20      (artifact prevention)
  G1 RETURN    mean_ann >= baseline + 2pp         (TRUE edge)
  G2 DD        mean_dd >= baseline - 5pp          (tolerans)
  G3 NEG       0 negatif pencere                  (consistency)
  G4 R-ADJ     r_adj >= baseline + 0.05           (risk-adjusted iyilesme)

PRE-REG NOT:
  - mean_best secimi: PASS arasindan en yuksek r-adj.
  - Cherry-pick yok: tum 9 hucre ayni pencere/trade-pool prosedurunden gecer.
  - Trade pool engine config'e bagli (mult/force_exit R outcome'unu degistirir),
    bu yuzden HER hucre icin POOL RE-GEN yapilir.
"""
from __future__ import annotations

import json
import os
import pickle
import sys
import warnings
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

# v1.3 stack: TOP_11 (TOP_10 + FVG)
TOP_11 = TOP_10 + [("fvg_fill_reversal", "FVGFillReversalStrategy")]

CACHE_DIR = ROOT / "data" / "_sec13_4_cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)
REPORT_PATH = ROOT / "reports" / "lab" / "sec13_4_engine_force_exit.md"
JSON_PATH = ROOT / "reports" / "lab" / "sec13_4_engine_force_exit.json"


# =====================================================================
# Pool generation (engine kwargs paramlandi)
# =====================================================================

def gather_with_engine(module_name, class_name, *,
                       runner_trail_mult, trail_activate_stage,
                       tp1_R, tp2_R, tp1_close_pct, tp2_close_pct,
                       runner_force_exit_method,
                       runner_force_exit_bars,
                       runner_force_exit_ema):
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
                runner_trail_mult=runner_trail_mult,
                trail_activate_stage=trail_activate_stage,
                tp1_R=tp1_R, tp2_R=tp2_R,
                tp1_close_pct=tp1_close_pct, tp2_close_pct=tp2_close_pct,
                runner_force_exit_method=runner_force_exit_method,
                runner_force_exit_bars=runner_force_exit_bars,
                runner_force_exit_ema=runner_force_exit_ema,
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


def build_pool_for_cell(cell_label, kwargs):
    """Pool gen + cache (per cell). v1.3 stack: TOP_11 + tp2_R=1.5 + tp1_R=1.0."""
    cache_p = CACHE_DIR / f"pool_{cell_label}.pkl"
    if cache_p.exists():
        with cache_p.open("rb") as f:
            return pickle.load(f)
    print(f"  [pool gen] {cell_label}  kwargs={kwargs}")
    pool = []
    for m, c in TOP_11:
        ts = gather_with_engine(m, c, **kwargs)
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
    """Single-trade R distribution — artifact gate."""
    if not trades:
        return {"max_R": 0, "p99_R": 0, "p95_R": 0, "n": 0}
    rs = [float(t["R"]) for t in trades]
    return {
        "max_R": max(rs),
        "p99_R": float(np.percentile(rs, 99)),
        "p95_R": float(np.percentile(rs, 95)),
        "min_R": min(rs),
        "mean_R": float(np.mean(rs)),
        "n": len(rs),
    }


# =====================================================================
# MAIN
# =====================================================================

# v1.3 stack defaults
V13_BASE = dict(
    runner_trail_mult=1.0,
    trail_activate_stage=2,
    tp1_R=1.0,
    tp2_R=1.5,
    tp1_close_pct=0.30,
    tp2_close_pct=0.30,
    runner_force_exit_method="atr_only",
    runner_force_exit_bars=None,
    runner_force_exit_ema=20,
)


def _cell(label, **overrides):
    kw = dict(V13_BASE)
    kw.update(overrides)
    return (label, kw)


def main():
    print("=" * 110)
    print("SEC13.4 — Engine Force-Exit + mult=2.0 Production-Safe Trailing")
    print("=" * 110)

    # Pre-registered grid (9 cell)
    GRID = [
        _cell("baseline_v1_3"),  # mult=1.0 + atr_only
        _cell("A1_mult2_atr_only", runner_trail_mult=2.0),
        _cell("A2_mult2_t20", runner_trail_mult=2.0,
              runner_force_exit_method="time", runner_force_exit_bars=20),
        _cell("A2_mult2_t30", runner_trail_mult=2.0,
              runner_force_exit_method="time", runner_force_exit_bars=30),
        _cell("A2_mult2_t50", runner_trail_mult=2.0,
              runner_force_exit_method="time", runner_force_exit_bars=50),
        _cell("A3_mult2_ema", runner_trail_mult=2.0,
              runner_force_exit_method="ema_cross"),
        _cell("A4_mult2_comb_t30",
              runner_trail_mult=2.0,
              runner_force_exit_method="combined",
              runner_force_exit_bars=30),
        _cell("A5_mult2_either_t30",
              runner_trail_mult=2.0,
              runner_force_exit_method="either",
              runner_force_exit_bars=30),
        _cell("A6_mult15_t30",
              runner_trail_mult=1.5,
              runner_force_exit_method="time",
              runner_force_exit_bars=30),
    ]

    # Build config (v1.3 production)
    base = ProductionConfig.from_yaml(str(ROOT / "configs" / "risk_balanced.yaml"))
    halt_cal = compute_btc_capitulation_halt()
    fund_long, fund_short = _lazy_build_funding_filters({
        "funding_filter_enabled": True,
        "funding_aggregation_mode": "00:00_only",
    })
    fng_short_20 = build_fng_short_skip(20)
    combined_short_skip = {**dict(fund_short or {}), **dict(fng_short_20)}
    cfg = base.with_overrides(
        alt_data_skip_long=fund_long,
        alt_data_skip_short=combined_short_skip,
        btc_halt_calendar=halt_cal,
        # v1.3 yaml zaten 0.06 / 21 — explicit ile sabitle
        monthly_dd=0.06,
        monthly_halt_days=21,
    )
    print(f"\nv1.3 cfg: mdd={cfg.monthly_dd}  halt={cfg.monthly_halt_days}d  "
          f"risk_pct={cfg.risk_pct}  short_skip={len(combined_short_skip)} gun\n")

    # Phase 1: Pool gen for each cell
    print("Phase 1: Pool gen (9 hucre × 11 strat × 11 sym)...")
    pools = {}
    for label, kw in GRID:
        pools[label] = build_pool_for_cell(label, kw)

    # Phase 2: Windows from baseline pool
    base_pool = pools["baseline_v1_3"]
    if not base_pool:
        print("FATAL: baseline pool empty.")
        return
    win_start = base_pool[0]["entry_ts"]
    win_end = base_pool[-1]["exit_ts"]
    windows = make_windows(win_start, win_end)
    print(f"\nPhase 2: {len(windows)} pencere, {win_start.date()} -> {win_end.date()}\n")

    # Phase 3: Evaluate each cell
    print("Phase 3: Walk-forward evaluation\n")
    print(f"{'cell':<24} {'n_trd':>6} {'mean_R':>7} {'maxR':>7} {'p99R':>7}  "
          f"{'mean_ann':>9} {'med':>7} {'min':>7} {'max':>7} "
          f"{'DD':>8} {'r-adj':>6} {'neg':>4}")
    print("-" * 130)

    results = []
    for label, kw in GRID:
        pool = pools[label]
        if not pool:
            print(f"{label:<24} EMPTY pool")
            continue
        art = pool_artifact_stats(pool)
        res = evaluate_pool(pool, cfg, windows)
        if res is None:
            print(f"{label:<24} eval=None")
            continue
        is_baseline = (label == "baseline_v1_3")
        tag = " <-- BASELINE" if is_baseline else ""
        print(f"{label:<24} {len(pool):>6d} "
              f"{art['mean_R']:>+6.2f} {art['max_R']:>+6.1f} {art['p99_R']:>+6.1f}  "
              f"{res['mean_ann']:>+8.2f}% {res['median_ann']:>+6.1f}% "
              f"{res['min_ann']:>+6.1f}% {res['max_ann']:>+6.1f}% "
              f"{res['mean_dd']:>+7.1f}% {res['r_adj']:>5.3f} "
              f"{res['negatives']:>4d}{tag}")
        results.append({
            "cell": label, "kwargs": kw, "n_trades": len(pool),
            **res,
            "max_R": art["max_R"], "p99_R": art["p99_R"],
            "p95_R": art["p95_R"], "mean_R": art["mean_R"],
            "is_baseline": is_baseline,
        })

    # Phase 4: Gates
    baseline = next((r for r in results if r["is_baseline"]), None)
    if not baseline:
        print("FATAL: baseline missing.")
        return
    b_ann = baseline["mean_ann"]
    b_dd = baseline["mean_dd"]
    b_radj = baseline["r_adj"]
    print(f"\nBASELINE v1.3 measured: ann={b_ann:+.2f}%  DD={b_dd:+.1f}%  "
          f"r-adj={b_radj:.3f}  neg={baseline['negatives']}\n")

    print("# GATES (per cell vs baseline):")
    print(f"  G0 ARTIFACT  max_R <= 20")
    print(f"  G1 RETURN    mean_ann >= {b_ann + 2.0:.2f}% (baseline +2pp)")
    print(f"  G2 DD        mean_dd >= {b_dd - 5.0:.1f}% (baseline -5pp tolerans)")
    print(f"  G3 NEG       negatives == 0")
    print(f"  G4 R-ADJ     r-adj >= {b_radj + 0.05:.3f} (baseline +0.05)\n")

    print(f"{'cell':<24} {'G0':>4} {'G1':>4} {'G2':>4} {'G3':>4} {'G4':>4} {'verdict':>8} "
          f"{'d_ann':>8} {'d_dd':>7} {'d_radj':>8} {'maxR':>7}")
    print("-" * 110)
    pass_cells = []
    for r in results:
        if r["is_baseline"]:
            print(f"{r['cell']:<24} {'-':>4} {'-':>4} {'-':>4} {'-':>4} {'-':>4} {'BASE':>8} "
                  f"{'-':>8} {'-':>7} {'-':>8} {r['max_R']:>+6.1f}")
            continue
        g0 = r["max_R"] <= 20.0
        g1 = r["mean_ann"] >= b_ann + 2.0
        g2 = r["mean_dd"] >= b_dd - 5.0
        g3 = r["negatives"] == 0
        g4 = r["r_adj"] >= b_radj + 0.05
        all_ok = g0 and g1 and g2 and g3 and g4
        verdict = "PASS" if all_ok else "fail"
        print(f"{r['cell']:<24} "
              f"{'OK' if g0 else 'XX':>4} "
              f"{'OK' if g1 else '..':>4} "
              f"{'OK' if g2 else '..':>4} "
              f"{'OK' if g3 else '..':>4} "
              f"{'OK' if g4 else '..':>4} "
              f"{verdict:>8} "
              f"{r['mean_ann']-b_ann:>+7.2f}pp {r['mean_dd']-b_dd:>+6.1f}pp "
              f"{r['r_adj']-b_radj:>+7.3f} {r['max_R']:>+6.1f}")
        if all_ok:
            pass_cells.append(r)

    print()
    winner = None
    if pass_cells:
        pass_cells.sort(key=lambda r: -r["r_adj"])
        winner = pass_cells[0]
        print(f"# WINNER (en yuksek r-adj among PASS):")
        print(f"  cell={winner['cell']}")
        print(f"  ann={winner['mean_ann']:+.2f}%  DD={winner['mean_dd']:+.1f}%  "
              f"r-adj={winner['r_adj']:.3f}  max_R={winner['max_R']:+.1f}")
        print(f"  delta vs baseline: ann {winner['mean_ann']-b_ann:+.2f}pp  "
              f"DD {winner['mean_dd']-b_dd:+.1f}pp  r-adj {winner['r_adj']-b_radj:+.3f}")
    else:
        print("# WINNER: NONE — hicbir hucre tum gate'leri (G0-G4) gecmedi.")
        non_base = [r for r in results if not r["is_baseline"]]
        if non_base:
            non_base.sort(key=lambda r: -r["r_adj"])
            top = non_base[0]
            print(f"  EN YUKSEK r-adj (PASS-DISI): {top['cell']} "
                  f"r-adj={top['r_adj']:.3f} ann={top['mean_ann']:+.2f}% "
                  f"DD={top['mean_dd']:+.1f}% maxR={top['max_R']:+.1f}")

    # Persist
    JSON_PATH.parent.mkdir(parents=True, exist_ok=True)
    with JSON_PATH.open("w", encoding="utf-8") as f:
        json.dump({
            "baseline": baseline,
            "results": results,
            "winner": winner,
            "n_windows": len(windows),
            "config": {
                "preset": "BALANCED+F&G+v1.3",
                "monthly_dd": cfg.monthly_dd,
                "halt_days": cfg.monthly_halt_days,
                "risk_pct": cfg.risk_pct,
                "tp1_R": V13_BASE["tp1_R"], "tp2_R": V13_BASE["tp2_R"],
            },
        }, f, indent=2, default=str)
    print(f"\nJSON saved: {JSON_PATH}")

    # Markdown report
    write_report(REPORT_PATH, results, baseline, winner, b_ann, b_dd, b_radj,
                 len(windows))
    print(f"MD saved:   {REPORT_PATH}")

    return results, winner


def write_report(path, results, baseline, winner, b_ann, b_dd, b_radj, n_windows):
    L = []
    L.append("# SEC13.4 — Engine Force-Exit + Production-Safe Trailing\n\n")
    L.append("**Tarih:** 2026-05-13  \n")
    L.append("**Sprint:** sec13_4_engine_force_exit  \n")
    L.append("**Walk-forward:** {} pencere (3y rolling, 60g step)  \n".format(n_windows))
    L.append("**Pool:** v1.3 (TOP_11 + tp1_R=1.0 + tp2_R=1.5 + monthly_dd=0.06 + halt=21)  \n")
    L.append("**Engine:** runner_force_exit (atr_only | time | ema_cross | combined | either)  \n\n")

    L.append("## Hipotez\n\n")
    L.append("SEC11.A grid'inde `runner_trail_mult=2.0` ATR cap=5R altinda +%45.4/yil real edge "
             "uretti, ancak naif backtestte single-trade R=967 fantasy artifact (runner backtest "
             "sonuna kadar tasinmis) edge'i +%212/yil yapay sisirdi. Engine'e force-exit "
             "(time / ema_cross / combined) eklenirse mult=2.0 production-safe olur.\n\n")

    L.append("## Pre-registered Grid\n\n")
    L.append("| cell | mult | exit_method | bars | ema |\n")
    L.append("|------|------|-------------|------|-----|\n")
    for r in results:
        kw = r["kwargs"]
        L.append(f"| {r['cell']} | {kw['runner_trail_mult']} | "
                 f"{kw['runner_force_exit_method']} | "
                 f"{kw.get('runner_force_exit_bars')} | "
                 f"{kw['runner_force_exit_ema']} |\n")
    L.append("\n")

    L.append("## Sonuclar (13 pencere walk-forward)\n\n")
    L.append("| cell | n_trd | mean_R | max_R | p99_R | mean_ann | DD | r-adj | neg |\n")
    L.append("|------|-------|--------|-------|-------|----------|-----|-------|-----|\n")
    for r in results:
        tag = " (baseline)" if r["is_baseline"] else ""
        L.append(f"| {r['cell']}{tag} | {r['n_trades']} | "
                 f"{r['mean_R']:+.2f} | {r['max_R']:+.1f} | {r['p99_R']:+.1f} | "
                 f"{r['mean_ann']:+.2f}% | {r['mean_dd']:+.1f}% | "
                 f"{r['r_adj']:.3f} | {r['negatives']}/{r['n_windows']} |\n")
    L.append("\n")

    L.append("## Statistical Gates\n\n")
    L.append(f"- **G0 ARTIFACT** max_R <= 20  (artifact prevention — fantasy R kontrolu)\n")
    L.append(f"- **G1 RETURN**   mean_ann >= {b_ann + 2.0:.2f}%  (baseline {b_ann:+.2f}% + 2pp)\n")
    L.append(f"- **G2 DD**       mean_dd >= {b_dd - 5.0:.1f}%  (baseline {b_dd:+.1f}% + 5pp tolerans)\n")
    L.append(f"- **G3 NEG**      negatives == 0\n")
    L.append(f"- **G4 R-ADJ**    r_adj >= {b_radj + 0.05:.3f}  (baseline {b_radj:.3f} + 0.05)\n\n")

    L.append("## Gate Verdict\n\n")
    L.append("| cell | G0 | G1 | G2 | G3 | G4 | verdict | d_ann | d_dd | d_radj | maxR |\n")
    L.append("|------|----|----|----|----|----|---------|-------|------|--------|------|\n")
    for r in results:
        if r["is_baseline"]:
            L.append(f"| {r['cell']} | — | — | — | — | — | BASE | — | — | — | {r['max_R']:+.1f} |\n")
            continue
        g0 = r["max_R"] <= 20.0
        g1 = r["mean_ann"] >= b_ann + 2.0
        g2 = r["mean_dd"] >= b_dd - 5.0
        g3 = r["negatives"] == 0
        g4 = r["r_adj"] >= b_radj + 0.05
        ok = g0 and g1 and g2 and g3 and g4
        L.append(f"| {r['cell']} | "
                 f"{'OK' if g0 else 'XX'} | "
                 f"{'OK' if g1 else '..'} | "
                 f"{'OK' if g2 else '..'} | "
                 f"{'OK' if g3 else '..'} | "
                 f"{'OK' if g4 else '..'} | "
                 f"{'**PASS**' if ok else 'fail'} | "
                 f"{r['mean_ann']-b_ann:+.2f}pp | {r['mean_dd']-b_dd:+.1f}pp | "
                 f"{r['r_adj']-b_radj:+.3f} | {r['max_R']:+.1f} |\n")
    L.append("\n")

    L.append("## Karar\n\n")
    if winner is not None:
        L.append(f"**WINNER:** `{winner['cell']}`  \n")
        kw = winner["kwargs"]
        L.append(f"- mult={kw['runner_trail_mult']}, "
                 f"method={kw['runner_force_exit_method']}, "
                 f"bars={kw.get('runner_force_exit_bars')}, "
                 f"ema={kw['runner_force_exit_ema']}\n")
        L.append(f"- yillik {winner['mean_ann']:+.2f}% "
                 f"(baseline {b_ann:+.2f}%, +{winner['mean_ann']-b_ann:.2f}pp)\n")
        L.append(f"- DD {winner['mean_dd']:+.1f}% "
                 f"(baseline {b_dd:+.1f}%, {winner['mean_dd']-b_dd:+.1f}pp)\n")
        L.append(f"- r-adj {winner['r_adj']:.3f} "
                 f"(baseline {b_radj:.3f}, +{winner['r_adj']-b_radj:.3f})\n")
        L.append(f"- max_R {winner['max_R']:+.1f}  (G0 artifact gate <= 20 OK)\n")
        L.append(f"- 13/13 pencere pozitif: EVET\n\n")
        L.append("**ONERI:** engine.py default'larini bu hucreye guncelle (geri uyumlu — "
                 "yeni kwarg, eski kullanimlar `atr_only`'de kalir).\n")
    else:
        L.append("**RED — hicbir hucre tum gate'leri (G0-G4) gecmedi.**\n\n")
        non_base = [r for r in results if not r["is_baseline"]]
        if non_base:
            non_base.sort(key=lambda r: -r["r_adj"])
            top = non_base[0]
            L.append(f"En yuksek r-adj non-PASS aday: `{top['cell']}` "
                     f"(r-adj {top['r_adj']:.3f}, ann {top['mean_ann']:+.2f}%, "
                     f"DD {top['mean_dd']:+.1f}%, max_R {top['max_R']:+.1f}).\n\n")
        L.append("Yorum: SEC11.A'da gorulen mult=2.0 +%45.4 (cap=5R) edge'i, force-exit "
                 "ile hayata gecirilemedi. Olasi sebepler:\n"
                 "- Time-based exit erken kapatip mevcut 1R-locked SL ile cogu trade'i "
                 "  break-even cevirdi (theoretical alpha kayboldu).\n"
                 "- EMA20 cross filter cogu trade'i daha trail aktive olmadan kapatti "
                 "  (1d crypto'da EMA20 cok hizli osillasyon).\n"
                 "- mult=2.0 ATR ile birlikte time/ema exit ekstra exit kaynagi olunca "
                 "  baseline mult=1.0 ATR trail'in dogal stop'una ekledigi opportunity "
                 "  cost net negatif.\n\n"
                 "Bu durumda **production v1.3 (mult=1.0 + atr_only) korunmali**, "
                 "engine'e force-exit hooks eklendi ama default DEGISTIRILMIYOR.\n")
    L.append("\n## Pre-Reg Disipline & Reproducibility\n\n")
    L.append("- Grid pre-registered (9 hucre, 5-aksiyon orthogonal).\n")
    L.append("- HARK protection: gates onceden yazildi, post-hoc gate-tweak yok.\n")
    L.append(f"- Trade pool cache: `data/_sec13_4_cache/pool_*.pkl` (9 hucre × ~7K trade).\n")
    L.append(f"- JSON: `reports/lab/sec13_4_engine_force_exit.json`\n")
    L.append("- Re-run: `PYTHONPATH=src python scripts/sec13_4_engine_force_exit.py`\n")
    L.append("- Engine API: `BacktestEngine(runner_force_exit_method='time'|'ema_cross'|"
             "'combined'|'either', runner_force_exit_bars=N, runner_force_exit_ema=N)`\n")
    with open(path, "w", encoding="utf-8") as f:
        f.writelines(L)


if __name__ == "__main__":
    main()
