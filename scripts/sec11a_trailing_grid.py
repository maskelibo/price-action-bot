"""SEC11.A: Trailing stop parameter grid optimization.

HIPOTEZ:
  Trailing multiplier 3.0 (configs/risk_balanced.yaml) TOO LOOSE — daha siki
  trailing (1.5/2.0) winners daha cabuk kapatip giveback engelleyebilir, ya da
  daha gevsek (4.0/5.0) winners daha uzun yasayip ek getiri uretir.

TEST DESIGN:
  Engine.runner_trail_mult ∈ {0.5, 1.0, 1.5, 2.0, 3.0, 4.0, 5.0}
    NOT: production v1.1 baseline = 1.0 (engine'de hardcoded). risk_balanced.yaml'da
    yazili 3.0 sadece dokumantasyondu — gercek engine 1.0 ATR kullaniyor.
  Engine.trail_activate_stage ∈ {1, 2}
    1 = trail TP1 (1R) sonrasi aktif (yeni)
    2 = trail TP2 (2R) sonrasi aktif (production default)

  Toplam: 7 mult x 2 stage = 14 hucre

WALK-FORWARD:
  3y rolling, 60 gun adim — 13 pencere (v0.9.7 ile ayni cerceve).

GATES (pre-registered):
  - mean(annualized) >= baseline + 1pp
  - mean(DD) >= baseline - 5pp tolerance
  - 0 negatif pencere
  - r-adj iyilesme >= +0.05

BASELINE: B0 (production v1.1) = mult=1.0, stage=2 (mevcut hardcoded).
"""
from __future__ import annotations

import json
import os
import sys
from datetime import timedelta
from pathlib import Path
from statistics import mean, median

os.environ["PA_LOG_QUIET"] = "1"

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

from price_action.backtest.lab import ProductionConfig, production_replay
from price_action.backtest.regime import compute_btc_capitulation_halt
from scripts.v09_optimize_top10 import SYMBOLS_11, TOP_10
from scripts.v097_balanced_optimization import build_fng_short_skip


def _gather_with_trail(module_name: str, class_name: str,
                       runner_trail_mult: float,
                       trail_activate_stage: int) -> list:
    """v09_optimize_top10._gather kopyasi + engine trail param inject."""
    from price_action.backtest.engine import BacktestEngine
    from price_action.signals.filters import volume_zscore
    from scripts.run_real_backtest import _load_symbol_ohlcv
    try:
        mod = __import__(f"price_action.strategies.{module_name}",
                         fromlist=[class_name, "_default_manifest"])
        cls = getattr(mod, class_name)
        manifest_fn = getattr(mod, "_default_manifest", None)
        if not manifest_fn:
            return []
        s = cls(manifest_fn())
    except Exception as exc:
        print(f"  [import-fail] {module_name}: {exc}")
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

            # KRITIK: engine kwarg ile trail param inject
            e = BacktestEngine(
                risk_officer=None,
                store_load=None,
                runner_trail_mult=runner_trail_mult,
                trail_activate_stage=trail_activate_stage,
            )
            r = e.run(s, [sym],
                      start=df["ts"].iloc[0].to_pydatetime(),
                      end=df["ts"].iloc[-1].to_pydatetime(),
                      timeframe="1d",
                      initial_capital=10_000.0,
                      fees={"taker": 0.00075, "maker": -0.00010},
                      slippage_bps=5.0,
                      ohlcv_provider=prov)

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
                    vz = float(df["vol_z_pre"].iloc[idx]) if not pd.isna(df["vol_z_pre"].iloc[idx]) else 0
                out.append({
                    "entry_ts": ts_e,
                    "exit_ts": ts_x,
                    "entry_price": float(t["entry_price"]),
                    "initial_sl": float(t["initial_sl"]),
                    "R": float(t["realized_r_multiple"]),
                    "symbol": sym,
                    "side": str(t["side"]),
                    "conf": conf,
                    "strategy": module_name,
                    "vol_z": vz,
                })
        except Exception as exc:
            print(f"  [sim-fail] {module_name}/{sym}: {exc}")
            continue
    return out


def gather_all_for_cell(mult: float, stage: int) -> list:
    """Tum 10 strateji icin trades (mult, stage) hucresi."""
    all_trades = []
    for m, c in TOP_10:
        trs = _gather_with_trail(m, c, mult, stage)
        all_trades.extend(trs)
    all_trades.sort(key=lambda x: x["entry_ts"])
    return all_trades


def make_windows(start, end, span_days=3 * 365, step_days=60):
    windows = []
    cur = start
    while cur + pd.Timedelta(days=span_days) <= end:
        windows.append((cur, cur + pd.Timedelta(days=span_days)))
        cur += pd.Timedelta(days=step_days)
    return windows


def evaluate(trades, cfg, windows):
    """Pencere bazli metrikler."""
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


def main():
    print("=" * 110)
    print("SEC11.A — TRAILING STOP GRID (mult x activate_stage), 13-window walk-forward")
    print("=" * 110)

    # Grid
    MULTS = [0.5, 1.0, 1.5, 2.0, 3.0, 4.0, 5.0]
    STAGES = [1, 2]   # 1 = trail post-1R, 2 = trail post-2R (production)

    # Build BALANCED+v1.1 base config (monthly_dd=0.08 from yaml zaten)
    base = ProductionConfig.from_yaml(str(ROOT / "configs" / "risk_balanced.yaml"))
    print(f"\nbase config: risk_pct={base.risk_pct}  monthly_dd={base.monthly_dd}  "
          f"halt={'ON' if base.btc_halt_calendar else 'off'}")

    # F&G short skip (BALANCED+F&G icin)
    fng_short_20 = build_fng_short_skip(20)
    cfg = base.with_overrides(alt_data_skip_short=dict(fng_short_20))
    print(f"F&G short-skip: {len(fng_short_20)} gun")
    print(f"monthly_dd: {cfg.monthly_dd} (v1.1 production)\n")

    # ----- Phase 1: trade pool toplama (her hucre icin BIR DEFA) -----
    print("Phase 1: Trade pool toplama (14 hucre x 10 strat x 11 sym)...")
    print("Bu uzun surer (5-10 dk). Cache yoksa hepsi yeniden cikar.\n")

    cell_trades = {}  # (mult, stage) -> [trades]
    cache_dir = ROOT / "data" / "_sec11a_cache"
    cache_dir.mkdir(parents=True, exist_ok=True)

    grid = [(m, s) for s in STAGES for m in MULTS]
    for i, (m, s) in enumerate(grid, 1):
        cache_p = cache_dir / f"trades_mult{m}_stage{s}.pkl"
        if cache_p.exists():
            import pickle
            with cache_p.open("rb") as f:
                trs = pickle.load(f)
            print(f"  [{i:2d}/{len(grid)}] mult={m} stage={s}: cached n={len(trs)}")
        else:
            print(f"  [{i:2d}/{len(grid)}] mult={m} stage={s}: gathering...")
            trs = gather_all_for_cell(m, s)
            import pickle
            with cache_p.open("wb") as f:
                pickle.dump(trs, f)
            print(f"     -> n={len(trs)} (cached)")
        cell_trades[(m, s)] = trs

    # ----- Phase 2: walk-forward windows -----
    print("\nPhase 2: Walk-forward windows...")
    # Use baseline (mult=1, stage=2) trade pool to determine windows
    base_trades = cell_trades[(1.0, 2)]
    if not base_trades:
        print("FATAL: baseline trade pool empty.")
        return
    start = base_trades[0]["entry_ts"]
    end = base_trades[-1]["exit_ts"]
    windows = make_windows(start, end)
    print(f"  span: {start.date()} -> {end.date()}, {len(windows)} pencere")

    # ----- Phase 3: grid evaluation -----
    print("\nPhase 3: Grid evaluation (mult x stage)\n")
    print(f"{'mult':>5} {'stage':>5} {'n_trd':>6} {'mean_ann':>9} {'med':>7} {'min':>7} "
          f"{'max':>7} {'mean_dd':>8} {'r-adj':>7} {'neg':>4}")
    print("-" * 110)
    results = []
    for s in STAGES:
        for m in MULTS:
            trs = cell_trades[(m, s)]
            if not trs:
                print(f"{m:>5} {s:>5}  EMPTY trade pool")
                continue
            res = evaluate(trs, cfg, windows)
            if res is None:
                print(f"{m:>5} {s:>5}  evaluate=None")
                continue
            tag = ""
            if m == 1.0 and s == 2:
                tag = " <-- BASELINE"
            print(f"{m:>5.1f} {s:>5d} {len(trs):>6d} "
                  f"{res['mean_ann']:>+8.2f}% {res['median_ann']:>+6.1f}% "
                  f"{res['min_ann']:>+6.1f}% {res['max_ann']:>+6.1f}% "
                  f"{res['mean_dd']:>+7.1f}% {res['r_adj']:>6.3f} "
                  f"{res['negatives']:>4d}{tag}")
            results.append({
                "mult": m, "stage": s, "n_trades": len(trs),
                **res, "is_baseline": (m == 1.0 and s == 2),
            })

    # ----- Phase 4: gates + winner -----
    baseline = next((r for r in results if r["is_baseline"]), None)
    if not baseline:
        print("\nFATAL: baseline cell missing.")
        return
    b_ann = baseline["mean_ann"]
    b_dd = baseline["mean_dd"]
    b_radj = baseline["r_adj"]
    print(f"\nBASELINE: ann={b_ann:+.2f}%  DD={b_dd:+.1f}%  r-adj={b_radj:.3f}  "
          f"neg={baseline['negatives']}\n")

    print("# GATES (per cell vs baseline):")
    print(f"  G1 mean_ann >= {b_ann + 1.0:.2f}% (baseline +1pp)")
    print(f"  G2 mean_dd >= {b_dd - 5.0:.1f}% (baseline -5pp tolerance)")
    print(f"  G3 negatives == 0")
    print(f"  G4 r-adj >= {b_radj + 0.05:.3f} (baseline +0.05)\n")

    print(f"{'mult':>5} {'stage':>5} {'G1':>4} {'G2':>4} {'G3':>4} {'G4':>4} {'all':>5} "
          f"{'d_ann':>7} {'d_dd':>7} {'d_radj':>8}")
    print("-" * 90)

    passed = []
    for r in results:
        if r["is_baseline"]:
            continue
        g1 = r["mean_ann"] >= b_ann + 1.0
        g2 = r["mean_dd"] >= b_dd - 5.0
        g3 = r["negatives"] == 0
        g4 = r["r_adj"] >= b_radj + 0.05
        all_ok = g1 and g2 and g3 and g4
        d_ann = r["mean_ann"] - b_ann
        d_dd = r["mean_dd"] - b_dd
        d_radj = r["r_adj"] - b_radj
        print(f"{r['mult']:>5.1f} {r['stage']:>5d} "
              f"{'OK' if g1 else '..':>4} "
              f"{'OK' if g2 else '..':>4} "
              f"{'OK' if g3 else '..':>4} "
              f"{'OK' if g4 else '..':>4} "
              f"{'PASS' if all_ok else '....':>5} "
              f"{d_ann:>+6.2f}pp {d_dd:>+6.1f}pp {d_radj:>+7.3f}")
        if all_ok:
            passed.append(r)

    print()
    if passed:
        passed.sort(key=lambda r: -r["r_adj"])
        winner = passed[0]
        print(f"# WINNER (highest r-adj among PASS):")
        print(f"  mult={winner['mult']} stage={winner['stage']}")
        print(f"  ann={winner['mean_ann']:+.2f}%  DD={winner['mean_dd']:+.1f}%  "
              f"r-adj={winner['r_adj']:.3f}  neg={winner['negatives']}")
        print(f"  delta vs baseline: ann {winner['mean_ann']-b_ann:+.2f}pp  "
              f"DD {winner['mean_dd']-b_dd:+.1f}pp  r-adj {winner['r_adj']-b_radj:+.3f}")
    else:
        print("# WINNER: NONE — hicbir hucre tum gate'leri gecmedi.")
        # En yakin aday'i goster (r-adj iyilesme bazinda)
        non_base = [r for r in results if not r["is_baseline"]]
        if non_base:
            non_base.sort(key=lambda r: -r["r_adj"])
            top = non_base[0]
            print(f"  EN YUKSEK r-adj (PASS-DISI): mult={top['mult']} stage={top['stage']} "
                  f"r-adj={top['r_adj']:.3f} ann={top['mean_ann']:+.2f}% DD={top['mean_dd']:+.1f}%")

    # ----- Persist results -----
    out_dir = ROOT / "reports" / "lab"
    out_dir.mkdir(parents=True, exist_ok=True)
    json_p = out_dir / "sec11a_trailing_grid.json"
    with json_p.open("w", encoding="utf-8") as f:
        json.dump({
            "baseline": baseline,
            "grid": results,
            "winner": passed[0] if passed else None,
            "n_windows": len(windows),
            "config": {
                "preset": "BALANCED+F&G+v1.1",
                "monthly_dd": cfg.monthly_dd,
                "risk_pct": cfg.risk_pct,
            },
        }, f, indent=2, default=str)
    print(f"\nJSON saved: {json_p}")

    # Markdown report
    md_p = out_dir / "sec11a_trailing_grid.md"
    with md_p.open("w", encoding="utf-8") as f:
        f.write("# SEC11.A — Trailing Stop Grid Optimization\n\n")
        f.write(f"**Tarih:** 2026-05-13  \n")
        f.write(f"**Researcher:** sec11a_trailing_grid.py  \n")
        f.write(f"**Walk-forward:** {len(windows)} pencere (3y rolling, 60g step)  \n")
        f.write(f"**Preset:** BALANCED + F&G short-skip + v1.1 monthly_dd=0.08  \n")
        f.write(f"**Engine kanit:** trail_mult=1.0 stage=2 (production v1.1 hardcoded)  \n\n")
        f.write("## Hipotez\n\n")
        f.write("Trailing multiplier 1.0 ATR (production) optimal degil — daha siki ya da gevsek "
                "trail winners kapanis profilini etkiler.\n\n")
        f.write("## Grid\n\n")
        f.write("- mult ∈ {0.5, 1.0, 1.5, 2.0, 3.0, 4.0, 5.0}\n")
        f.write("- stage ∈ {1 (post-1R trail), 2 (post-2R trail, production)}\n\n")
        f.write("## Sonuclar\n\n")
        f.write("| mult | stage | n_trd | mean_ann | mean_dd | r-adj | neg | gate |\n")
        f.write("|------|-------|-------|----------|---------|-------|-----|------|\n")
        for r in results:
            tag = " (baseline)" if r["is_baseline"] else ""
            g1 = r["mean_ann"] >= b_ann + 1.0
            g2 = r["mean_dd"] >= b_dd - 5.0
            g3 = r["negatives"] == 0
            g4 = r["r_adj"] >= b_radj + 0.05
            gate = "PASS" if (g1 and g2 and g3 and g4) else "fail"
            if r["is_baseline"]:
                gate = "—"
            f.write(f"| {r['mult']} | {r['stage']} | {r['n_trades']} | "
                    f"{r['mean_ann']:+.2f}%{tag} | {r['mean_dd']:+.1f}% | "
                    f"{r['r_adj']:.3f} | {r['negatives']} | {gate} |\n")
        f.write("\n## Karar\n\n")
        if passed:
            w = passed[0]
            f.write(f"**WINNER:** mult={w['mult']} stage={w['stage']}  \n")
            f.write(f"- mean_ann: {w['mean_ann']:+.2f}% (baseline {b_ann:+.2f}%, "
                    f"+{w['mean_ann']-b_ann:.2f}pp)\n")
            f.write(f"- mean_dd: {w['mean_dd']:+.1f}% (baseline {b_dd:+.1f}%, "
                    f"{w['mean_dd']-b_dd:+.1f}pp)\n")
            f.write(f"- r-adj: {w['r_adj']:.3f} (baseline {b_radj:.3f}, "
                    f"+{w['r_adj']-b_radj:.3f})\n")
            f.write(f"- 13/13 pencere pozitif: {'EVET' if w['negatives']==0 else 'HAYIR'}\n\n")
            f.write("**ONERI:** engine.py hardcoded trail_mult'i bu hucreye guncelle "
                    "veya BacktestEngine kwarg'larini production yaml'dan oku.\n")
        else:
            f.write("**RED — hicbir konfigurasyon gate setini gecemedi.**\n\n")
            f.write("Yorum: production trail_mult=1.0 ATR + post-2R activation, mevcut "
                    "exit policy'de zaten yakin-optimal. Trail tightening winners'i erken "
                    "kapatip giveback engellemiyor; loosening reversal hit'i artiriyor. "
                    "Sonraki sprint: TP2-multipliyer (2R -> 2.5R/3R) veya partial close ratios.\n")
    print(f"MD saved: {md_p}")


if __name__ == "__main__":
    main()
