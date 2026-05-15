"""SEC25 - Brooks DB Bull Flag honest audit.

Default config standalone shows n=31 mR=+0.638 ETH 2022-04 outlier R=+12.79 60d hold.
SEC19/SEC11/SEC15 engine `trail_activate_stage=2` default fantasy R artifact.

This audit runs the BEST naive-p configs (idx=0, idx=12) with HONEST clip
(hold>30d -> R<=1.0) and reports artifact-controlled metrics + p_shuffle.

Configs tested:
  C0 (idx=0)  : equal_pct=0.03, flag_bars=3, body=0.30   -> n=109 mR=+0.510 p_naive=0.001
  C12 (idx=12): equal_pct=0.08, flag_bars=3, body=0.30   -> n=247 mR=+0.245 p_naive=0.009
  Default      : equal_pct=0.03, flag_bars=5, body=0.40   -> n=31

Comparison: clip threshold {none, hold>60d->1, hold>30d->1, R<=3, R<=2}.
"""
from __future__ import annotations

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


def _shuffle_p(Rs, n_perm=2000, seed=42):
    if len(Rs) == 0:
        return None
    Rs = np.array(Rs, dtype=float)
    obs = float(Rs.sum())
    rng = np.random.default_rng(seed)
    null_sums = np.array([(Rs * rng.choice([-1, 1], size=len(Rs))).sum()
                          for _ in range(n_perm)])
    return float((null_sums >= obs).mean())


def _gather_with_config(params, universe):
    from price_action.backtest.engine import BacktestEngine
    from price_action.strategies.brooks_db_bull_flag import (
        _default_manifest, BrooksDBBullFlagStrategy,
    )
    from scripts.run_real_backtest import _load_symbol_ohlcv

    manifest = _default_manifest()
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
                out.append({
                    "entry_ts": entry_ts,
                    "exit_ts": exit_ts,
                    "hold_d": hold_d,
                    "R_raw": R_raw,
                    "symbol": sym,
                    "side": str(t["side"]),
                })
        except Exception as exc:
            print(f"   ERR {sym}: {exc}")
            continue
    return out


def _apply_clip(trades, mode):
    """Return list of clipped R values based on mode."""
    Rs = []
    for t in trades:
        r = t["R_raw"]
        if mode == "none":
            pass
        elif mode == "hold60":
            if t["hold_d"] > 60:
                r = min(r, 1.0)
        elif mode == "hold30":
            if t["hold_d"] > 30:
                r = min(r, 1.0)
        elif mode == "hold15":
            if t["hold_d"] > 15:
                r = min(r, 1.0)
        elif mode == "cap5":
            r = min(r, 5.0)
        elif mode == "cap3":
            r = min(r, 3.0)
        elif mode == "cap2":
            r = min(r, 2.0)
        Rs.append(r)
    return Rs


def _audit(name, trades, universe):
    print(f"\n=== {name} ===")
    print(f"  trades n = {len(trades)}")
    if not trades:
        return

    holds = [t["hold_d"] for t in trades]
    print(f"  hold_d:  min={min(holds)}  p50={np.median(holds):.0f}  p75={np.percentile(holds,75):.0f}  "
          f"p90={np.percentile(holds,90):.0f}  max={max(holds)}")

    pct_long_hold = sum(1 for h in holds if h > 30) / len(holds) * 100
    print(f"  pct hold>30d:  {pct_long_hold:.1f}%   pct hold>60d:  "
          f"{sum(1 for h in holds if h>60)/len(holds)*100:.1f}%")

    Rs_raw = [t["R_raw"] for t in trades]
    print(f"  R_raw:   min={min(Rs_raw):.2f}  max={max(Rs_raw):.2f}  "
          f"mean={np.mean(Rs_raw):+.3f}  median={np.median(Rs_raw):+.3f}")

    print()
    print(f"  {'clip mode':<12} {'mR':>8} {'WR%':>5} {'p_shuf':>7} {'max_R':>6} {'symdev':>7} {'pos_syms':>8}")
    for mode in ("none", "hold60", "hold30", "hold15", "cap5", "cap3", "cap2"):
        Rs = _apply_clip(trades, mode)
        arr = np.array(Rs)
        mR = float(arr.mean())
        WR = float((arr > 0).mean())
        max_R = float(arr.max())
        p = _shuffle_p(Rs)

        # symdev
        by_sym = {}
        for t, r in zip(trades, Rs):
            by_sym.setdefault(t["symbol"], []).append(r)
        if mR == 0 or abs(mR) < 1e-6:
            symdev = None
        else:
            devs = []
            for sym_excl in universe:
                rs = [r for t, r in zip(trades, Rs) if t["symbol"] != sym_excl]
                if rs:
                    devs.append(abs((np.mean(rs) - mR) / abs(mR)))
            symdev = max(devs) if devs else None
        pos = sum(1 for v in by_sym.values() if np.mean(v) > 0)

        sd_str = f"{symdev*100:.0f}%" if symdev is not None else "NA"
        print(f"  {mode:<12} {mR:+8.3f} {WR*100:5.1f} {p:7.3f} {max_R:6.2f} {sd_str:>7}  {pos}/{len(by_sym)}")

    # Year breakdown (using hold>30 clip)
    Rs_clip = _apply_clip(trades, "hold30")
    by_year = {}
    for t, r in zip(trades, Rs_clip):
        y = t["entry_ts"].year
        by_year.setdefault(y, []).append(r)
    print(f"\n  Per-year (hold>30d clip):")
    for y in sorted(by_year):
        vs = by_year[y]
        print(f"    {y}: n={len(vs):3d} mR={np.mean(vs):+.3f}")


def main():
    configs = {
        "DEFAULT (eq=0.03 fb=5 body=0.40)": {
            "equal_pct": 0.03, "flag_bars": 5, "flag_rng_atr": 4.0,
            "body_ratio_min": 0.40, "fractal_n": 2,
        },
        "C0 (eq=0.03 fb=3 body=0.30) - best mR with n>100": {
            "equal_pct": 0.03, "flag_bars": 3, "flag_rng_atr": 4.0,
            "body_ratio_min": 0.30, "fractal_n": 2,
        },
        "C7 (eq=0.05 fb=3 body=0.40) - mid mR, n=154": {
            "equal_pct": 0.05, "flag_bars": 3, "flag_rng_atr": 4.0,
            "body_ratio_min": 0.40, "fractal_n": 2,
        },
        "C12 (eq=0.08 fb=3 body=0.30) - n=247 reached n_min": {
            "equal_pct": 0.08, "flag_bars": 3, "flag_rng_atr": 4.0,
            "body_ratio_min": 0.30, "fractal_n": 2,
        },
    }

    all_results = {}
    for name, params in configs.items():
        trades = _gather_with_config(params, SYMBOLS_11)
        _audit(name, trades, SYMBOLS_11)
        all_results[name] = {
            "params": params,
            "n_trades": len(trades),
        }

    print()
    print("=" * 100)
    print("CONCLUSION GUIDANCE")
    print("=" * 100)
    print(
        "Honest clip (hold>30d->R<=1) is SEC22-24 disciplined metric.\n"
        "If mR_clip30 >= +0.10 AND p_shuf < 0.05 AND n >= 200 AND symdev < 30%\n"
        "   -> PASS-MARGINAL (still needs Bonferroni adj for the 18 configs)\n"
        "If mR_clip30 < +0.10 OR p_shuf >= 0.05 -> RED (artifact-controlled fail).\n"
    )

    out_dir = ROOT / "reports" / "researcher"
    out_dir.mkdir(parents=True, exist_ok=True)
    with open(out_dir / "sec25_brooks_db_honest_audit.json", "w") as f:
        json.dump(all_results, f, indent=2, default=str)


if __name__ == "__main__":
    main()
