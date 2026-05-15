"""Sec24 - Turtle Soup parameter grid drill + asymmetry exploration.

Pre-registered parametre grid:
  lookback in {15, 20, 25}
  body_ratio_min in {0.30, 0.40, 0.50}
  atr_min in {0.005, 0.010}

Bonferroni alpha = 0.05/18 = 0.00278.

Plus asymmetry probe:
  - short-only variant
  - bear-regime conditional (close < EMA200)

This is a SELECTION-BIAS-GUARDED sweep: if any config PASS hard gates,
follow-up OOS hold-out 2024-2025 validation REQUIRED before any production
candidacy (SEC23 paradigm).
"""
from __future__ import annotations

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

GATE = {"n_min": 200, "mR_min": 0.10, "WR_min": 0.45, "p_max": 0.05, "max_R_max": 10.0}


def _make_strategy(lookback, body_min, atr_min):
    from price_action.strategies.base import StrategyManifest
    from price_action.strategies.turtle_soup_20d import TurtleSoup20DStrategy
    raw = {
        "name": "turtle_soup_20d",
        "version": "1.0.0",
        "trend_filter": {"type": "ema", "period": 50, "required": False},
        "signals": {
            "patterns": [
                {
                    "id": "turtle_soup_short",
                    "enabled": True,
                    "weight": 2.0,
                    "params": {
                        "lookback_bars": int(lookback),
                        "body_ratio_min": float(body_min),
                        "upper_wick_min_ratio": 0.50,
                        "sl_atr_mult": 0.25,
                        "tp_r_multiple": 2.0,
                        "impulse_atr_mult": 2.0,
                        "atr_min_pct": float(atr_min),
                        "cooldown_bars": 3,
                    },
                },
                {
                    "id": "turtle_soup_long",
                    "enabled": True,
                    "weight": 2.0,
                    "params": {
                        "lookback_bars": int(lookback),
                        "body_ratio_min": float(body_min),
                        "lower_wick_min_ratio": 0.50,
                        "sl_atr_mult": 0.25,
                        "tp_r_multiple": 2.0,
                        "impulse_atr_mult": 2.0,
                        "atr_min_pct": float(atr_min),
                        "cooldown_bars": 3,
                    },
                },
            ],
            "filters": {"atr_min_pct": float(atr_min), "volume_zscore_min": 0.0},
            "confluence": {"method": "weighted_sum", "min_score": 1.5, "bonus_if_at_sr": 0.0},
        },
        "risk": {"take_profit": {"primary_R": 2.0}},
    }
    return TurtleSoup20DStrategy(StrategyManifest.model_validate(raw))


def _gather(strategy, universe):
    from price_action.backtest.engine import BacktestEngine
    from scripts.run_real_backtest import _load_symbol_ohlcv

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
                    "entry_ts": entry_ts, "exit_ts": exit_ts, "hold_d": hold_d,
                    "R": R, "R_raw": R_raw, "symbol": sym, "side": str(t["side"]),
                })
        except Exception:
            continue
    return out


def _shuffle_p(trades, n_perm=1000, seed=42):
    if not trades:
        return None
    Rs = np.array([t["R"] for t in trades], dtype=float)
    obs = float(Rs.sum())
    rng = np.random.default_rng(seed)
    null_sums = []
    for _ in range(n_perm):
        signs = rng.choice([-1, 1], size=len(Rs))
        null_sums.append((Rs * signs).sum())
    return float((np.array(null_sums) >= obs).mean())


def _row(trades, label, side_filter=None):
    if side_filter:
        trades = [t for t in trades if t["side"] == side_filter]
    if not trades:
        return {"label": label, "n": 0, "mR": 0.0, "WR": 0.0, "p": 1.0, "max_R": 0.0, "sumR": 0.0}
    Rs = np.array([t["R"] for t in trades], dtype=float)
    return {
        "label": label,
        "n": len(trades),
        "mR": float(Rs.mean()),
        "WR": float((Rs > 0).mean()),
        "p": _shuffle_p(trades, n_perm=1000),
        "max_R": float(Rs.max()),
        "sumR": float(Rs.sum()),
    }


def _gate_pass(row):
    return (row["n"] >= GATE["n_min"] and
            row["mR"] >= GATE["mR_min"] and
            row["WR"] >= GATE["WR_min"] and
            row["p"] < GATE["p_max"] and
            row["max_R"] < GATE["max_R_max"])


def main():
    print("=" * 100)
    print("Sec24 - Turtle Soup parameter grid drill + asymmetry probe")
    print("=" * 100)
    print()

    lookbacks = [15, 20, 25]
    body_mins = [0.30, 0.40, 0.50]
    atr_mins = [0.005, 0.010]

    n_configs = len(lookbacks) * len(body_mins) * len(atr_mins)
    bonf_alpha = 0.05 / n_configs

    print(f"Grid: lookback={lookbacks}, body_min={body_mins}, atr_min={atr_mins}")
    print(f"Total configs: {n_configs}  |  Bonferroni alpha = 0.05/{n_configs} = {bonf_alpha:.5f}")
    print()

    rows = []
    for lb in lookbacks:
        for bm in body_mins:
            for am in atr_mins:
                key = f"lb={lb}/body={bm:.2f}/atr={am:.3f}"
                print(f"  {key} ...", end=" ", flush=True)
                strategy = _make_strategy(lb, bm, am)
                trades = _gather(strategy, SYMBOLS_11)
                r_all = _row(trades, key + " ALL")
                r_short = _row(trades, key + " SHORT", side_filter="short")
                r_long = _row(trades, key + " LONG", side_filter="long")
                rows.append({"key": key, "lb": lb, "bm": bm, "am": am,
                            "all": r_all, "short": r_short, "long": r_long})
                print(f"n={r_all['n']:4d}  mR={r_all['mR']:+.3f}  WR={r_all['WR']*100:4.1f}%  "
                      f"p={r_all['p']:.3f}  | SHORT n={r_short['n']:4d} mR={r_short['mR']:+.3f}  "
                      f"LONG n={r_long['n']:4d} mR={r_long['mR']:+.3f}")

    print()
    print("=" * 100)
    print("ALL-CONFIG GATE PASS SUMMARY")
    print("=" * 100)

    # Top by mR (combined)
    rows_sorted = sorted(rows, key=lambda r: -r["all"]["mR"])
    print("\nTop 5 by ALL mR:")
    for r in rows_sorted[:5]:
        a = r["all"]
        gate = "PASS" if _gate_pass(a) else "fail"
        bonf = "BONF" if a["p"] < bonf_alpha else "    "
        print(f"  [{gate}] [{bonf}] {r['key']:<35}  n={a['n']:4d}  mR={a['mR']:+.3f}  "
              f"WR={a['WR']*100:5.1f}%  p={a['p']:.4f}  sumR={a['sumR']:+.2f}")

    # Top by SHORT mR
    rows_sorted_short = sorted(rows, key=lambda r: -r["short"]["mR"])
    print("\nTop 5 by SHORT-only mR:")
    for r in rows_sorted_short[:5]:
        s = r["short"]
        gate = "PASS" if _gate_pass(s) else "fail"
        bonf = "BONF" if s["p"] < bonf_alpha else "    "
        print(f"  [{gate}] [{bonf}] {r['key']:<35}  n={s['n']:4d}  mR={s['mR']:+.3f}  "
              f"WR={s['WR']*100:5.1f}%  p={s['p']:.4f}  sumR={s['sumR']:+.2f}")

    # Top by LONG mR
    rows_sorted_long = sorted(rows, key=lambda r: -r["long"]["mR"])
    print("\nTop 5 by LONG-only mR:")
    for r in rows_sorted_long[:5]:
        l = r["long"]
        gate = "PASS" if _gate_pass(l) else "fail"
        bonf = "BONF" if l["p"] < bonf_alpha else "    "
        print(f"  [{gate}] [{bonf}] {r['key']:<35}  n={l['n']:4d}  mR={l['mR']:+.3f}  "
              f"WR={l['WR']*100:5.1f}%  p={l['p']:.4f}  sumR={l['sumR']:+.2f}")

    print()
    print("=" * 100)
    print(f"BONFERRONI-CORRECTED PASS (alpha={bonf_alpha:.5f})")
    print("=" * 100)
    pass_count = sum(1 for r in rows if _gate_pass(r["all"]) and r["all"]["p"] < bonf_alpha)
    pass_short_count = sum(1 for r in rows if _gate_pass(r["short"]) and r["short"]["p"] < bonf_alpha)
    pass_long_count = sum(1 for r in rows if _gate_pass(r["long"]) and r["long"]["p"] < bonf_alpha)
    print(f"  All-direction PASS+Bonf: {pass_count} / {n_configs}")
    print(f"  Short-only PASS+Bonf:    {pass_short_count} / {n_configs}")
    print(f"  Long-only PASS+Bonf:     {pass_long_count} / {n_configs}")

    # Save
    import json
    out_path = ROOT / "reports" / "researcher" / "sec24_turtle_soup_drill.json"
    with open(out_path, "w") as f:
        json.dump([
            {
                "key": r["key"],
                "lb": r["lb"], "bm": r["bm"], "am": r["am"],
                "all": r["all"], "short": r["short"], "long": r["long"],
            }
            for r in rows
        ], f, indent=2, default=str)
    print(f"\nSaved: {out_path}")


if __name__ == "__main__":
    main()
