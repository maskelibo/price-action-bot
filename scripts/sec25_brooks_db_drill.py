"""SEC25 - Brooks DB Bull Flag parameter grid drill.

Default config: n=31 (HARD FAIL gate n>=200). Brooks/Bulkowski calibration
stocks/FX based — crypto frequency probable cause. Drill relaxes:
  - equal_pct: 0.03 -> {0.03, 0.05, 0.08} (price-equality looser)
  - flag_bars: 5 -> {3, 5, 7} (shorter/longer consol)
  - flag_rng_atr: 4.0 -> {4.0, 5.0, 6.0} (looser tightness)
  - body_ratio_min: 0.40 -> {0.30, 0.40, 0.50}
  - fractal_n: 2 -> {1, 2} (smaller swing window for more pivots)

Total: 3 x 3 x 3 x 3 x 2 = 162 configs (full Cartesian).
We'll run a SMARTER reduced grid: 18 configs (3 strong axes).

Bonferroni-aware: alpha = 0.05 / k_configs.

Hard gates per-config (RED if any FAIL):
  - n >= 200
  - mR >= +0.10
  - WR >= 0.45
  - p_shuffle < (0.05/k_effective)
  - max_R < 10
  - per_sym_pos >= 6 / 11
  - symout_dev < 30%

Honest R clip: hold>60d -> R<=1.0.
"""
from __future__ import annotations

import itertools
import json
import os
import sys
from pathlib import Path

os.environ["PA_LOG_QUIET"] = "1"

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

SYMBOLS_11 = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT",
              "ADA/USDT", "AVAX/USDT", "LINK/USDT", "DOT/USDT",
              "DOGE/USDT", "XRP/USDT", "MATIC/USDT"]


def _shuffle_p(trades, n_perm=2000, seed=42):
    if not trades:
        return None
    Rs = np.array([t["R"] for t in trades], dtype=float)
    obs = float(Rs.sum())
    rng = np.random.default_rng(seed)
    null_sums = np.array([(Rs * rng.choice([-1, 1], size=len(Rs))).sum()
                          for _ in range(n_perm)])
    return float((null_sums >= obs).mean())


def _symout_max_dev(trades, universe):
    if not trades:
        return None
    Rs_full = np.array([t["R"] for t in trades], dtype=float)
    mR_full = float(Rs_full.mean()) if len(Rs_full) else 0.0
    if abs(mR_full) < 1e-6:
        return None
    devs = []
    for sym_excl in universe:
        Rs = np.array([t["R"] for t in trades if t["symbol"] != sym_excl], dtype=float)
        if len(Rs) == 0:
            continue
        mR = float(Rs.mean())
        dev = (mR - mR_full) / abs(mR_full)
        devs.append(abs(dev))
    return float(max(devs)) if devs else None


def _gather_with_config(params, universe):
    """Run strategy with custom params override and gather trades."""
    from price_action.backtest.engine import BacktestEngine
    from price_action.strategies.brooks_db_bull_flag import (
        _default_manifest, BrooksDBBullFlagStrategy,
    )
    from scripts.run_real_backtest import _load_symbol_ohlcv

    # Patch the default manifest with custom params (in-memory override)
    manifest = _default_manifest()
    # patterns is a list of _PatternCfg pydantic objects; both long+short share keys
    for p in manifest.signals.patterns:
        for k, v in params.items():
            if k in ("equal_pct", "flag_bars", "flag_rng_atr",
                     "body_ratio_min", "fractal_n", "k_min", "k_max",
                     "j_min", "j_max"):
                p.params[k] = v

    strategy = BrooksDBBullFlagStrategy(manifest)

    out = []
    for sym in universe:
        try:
            df = _load_symbol_ohlcv(sym, tf="1d")
            if df is None or df.empty:
                continue
            df = df.sort_values("ts").reset_index(drop=True)
            df["symbol"] = sym
            df["venue"] = "binance"
            df["timeframe"] = "1d"
            def prov(*a, **k):
                return df.copy()
            e = BacktestEngine(risk_officer=None, store_load=None)
            r = e.run(strategy, [sym],
                     start=df["ts"].iloc[0].to_pydatetime(),
                     end=df["ts"].iloc[-1].to_pydatetime(),
                     timeframe="1d",
                     initial_capital=10_000.0,
                     fees={"taker": 0.00075, "maker": -0.00010},
                     slippage_bps=5.0,
                     ohlcv_provider=prov)
            for _, t in r.trades.iterrows():
                entry_ts = pd.Timestamp(t["entry_ts"])
                exit_ts = pd.Timestamp(t["exit_ts"])
                hold_d = (exit_ts - entry_ts).days
                R_raw = float(t["realized_r_multiple"])
                R = R_raw if hold_d <= 60 else min(R_raw, 1.0)
                out.append({
                    "entry_ts": entry_ts,
                    "exit_ts": exit_ts,
                    "hold_d": hold_d,
                    "R": R,
                    "R_raw": R_raw,
                    "symbol": sym,
                    "side": str(t["side"]),
                })
        except Exception as exc:
            print(f"   ERR {sym}: {exc}")
            continue
    return out


def _summarize(trades, universe):
    if not trades:
        return {"n": 0, "mR": 0.0, "WR": 0.0, "max_R": 0.0,
                "p_shuffle": None, "symout_dev": None, "pos_syms": 0}
    Rs = np.array([t["R"] for t in trades])
    by_sym = {}
    for t in trades:
        by_sym.setdefault(t["symbol"], []).append(t["R"])
    pos_syms = sum(1 for v in by_sym.values() if np.mean(v) > 0)
    return {
        "n": len(trades),
        "mR": float(Rs.mean()),
        "WR": float((Rs > 0).mean()),
        "max_R": float(Rs.max()),
        "p_shuffle": _shuffle_p(trades),
        "symout_dev": _symout_max_dev(trades, universe),
        "pos_syms": pos_syms,
        "n_long": sum(1 for t in trades if t["side"] == "long"),
        "n_short": sum(1 for t in trades if t["side"] == "short"),
    }


def main():
    # Grid: 18 configs (3 strong axes, 6 secondary combos)
    grid = []
    for equal_pct in [0.03, 0.05, 0.08]:
        for flag_bars in [3, 5, 7]:
            for body_min in [0.30, 0.40]:
                grid.append({
                    "equal_pct": equal_pct,
                    "flag_bars": flag_bars,
                    "flag_rng_atr": 4.0,  # fixed
                    "body_ratio_min": body_min,
                    "fractal_n": 2,        # fixed
                })

    k = len(grid)
    bonf_alpha = 0.05 / k
    print(f"GRID: {k} configs, Bonferroni alpha = 0.05/{k} = {bonf_alpha:.5f}")
    print()
    print(f"{'idx':>3}  {'eq':>5} {'fb':>3} {'rng':>4} {'body':>5}  {'n':>5} {'mR':>7} {'WR%':>5} {'maxR':>6} {'p':>7} {'symdev':>7} {'pos':>4}  GATE")
    print("-" * 110)

    results = []
    for idx, params in enumerate(grid):
        trades = _gather_with_config(params, SYMBOLS_11)
        s = _summarize(trades, SYMBOLS_11)
        s["params"] = params
        s["idx"] = idx
        results.append(s)

        # Hard gate (Bonferroni-adjusted p)
        fails = []
        if s["n"] < 200:
            fails.append(f"n={s['n']}")
        if s["mR"] < 0.10:
            fails.append(f"mR={s['mR']:.3f}")
        if s["WR"] < 0.45:
            fails.append(f"WR={s['WR']:.2f}")
        p_v = s["p_shuffle"]
        if p_v is None or p_v >= bonf_alpha:
            fails.append(f"p={p_v}")
        if s["max_R"] >= 10.0:
            fails.append(f"maxR={s['max_R']:.2f}")
        if s["pos_syms"] < 6:
            fails.append(f"pos={s['pos_syms']}")
        if s["symout_dev"] is None or s["symout_dev"] > 0.30:
            fails.append(f"sdev={s['symout_dev']}")
        verdict = "PASS" if not fails else "FAIL"
        s["verdict"] = verdict
        s["fails"] = fails

        p_str = f"{s['p_shuffle']:.3f}" if s["p_shuffle"] is not None else "NA"
        sdev_str = f"{s['symout_dev']*100:.0f}%" if s["symout_dev"] is not None else "NA"
        print(f"{idx:3d}  {params['equal_pct']:5.2f} {params['flag_bars']:3d} {params['flag_rng_atr']:4.1f} "
              f"{params['body_ratio_min']:5.2f}  {s['n']:5d} {s['mR']:+7.3f} {s['WR']*100:5.1f} "
              f"{s['max_R']:6.2f} {p_str:>7} {sdev_str:>7} {s['pos_syms']:4d}  {verdict}")

    # Naive p<0.05 ranking (selection bias warning - but useful diagnostic)
    print()
    print("=" * 110)
    print("BEST 5 BY mR (DESC) — selection-bias-warned")
    print("=" * 110)
    sorted_results = sorted(results, key=lambda x: -x["mR"])
    for s in sorted_results[:5]:
        print(f"  idx={s['idx']:2d}  params={s['params']}  ->  "
              f"n={s['n']} mR={s['mR']:+.3f} WR={s['WR']*100:.1f}% "
              f"p={s['p_shuffle']:.3f}  pos={s['pos_syms']}/11")

    # Count of PASS configs (Bonferroni strict)
    passes = [r for r in results if r["verdict"] == "PASS"]
    naive_pass = [r for r in results if (r["n"] >= 200 and r["mR"] >= 0.10
                                          and r["WR"] >= 0.45 and r["p_shuffle"] is not None
                                          and r["p_shuffle"] < 0.05 and r["max_R"] < 10
                                          and r["pos_syms"] >= 6
                                          and (r["symout_dev"] is None or r["symout_dev"] <= 0.30))]
    print()
    print(f"PASS COUNT (Bonferroni strict, alpha={bonf_alpha:.5f}): {len(passes)} / {k}")
    print(f"PASS COUNT (naive p<0.05, with all other gates): {len(naive_pass)} / {k}")
    print()
    if naive_pass:
        print("Naive p<0.05 PASS configs (selection-bias warned, OOS hold-out required):")
        for r in naive_pass:
            print(f"  {r['params']}  -> n={r['n']} mR={r['mR']:+.3f} p={r['p_shuffle']:.3f}")

    out_dir = ROOT / "reports" / "researcher"
    out_dir.mkdir(parents=True, exist_ok=True)
    drill_path = out_dir / "sec25_brooks_db_drill.json"
    with open(drill_path, "w") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\nResults saved: {drill_path}")


if __name__ == "__main__":
    main()
