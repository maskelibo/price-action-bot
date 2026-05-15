"""Sec22: HTF (High-Tight Flag) retest.

SEC19 backlog: HTF n=35 yetersiz, shuffle p=0.40 null. Backlog önerisi:
  - pole_min 0.60 → 0.40 sweep (parabolik kosul rahatlasin)
  - Alt-coin only universe (BTC/ETH HARIC) — pattern alt-coin parabolik dinamiğine ait

Test matrisi:
  - pole_min: {0.40, 0.45, 0.50, 0.55, 0.60 (default)}
  - Universe A: TUM_11_SYM (sanity)
  - Universe B: ALT_ONLY (BTC ve ETH HARIC) = 9 sym
  - HARD gate: n>=200, mR>+0.15, shuffle p<0.05, max_R<10 (artifact)

Edge gate gecen kombinasyon varsa: PASS aday listesi (engineering slot fix sonrasi
ensemble retest icin).
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

ALT_ONLY = [s for s in SYMBOLS_11 if s not in ("BTC/USDT", "ETH/USDT")]

POLE_MIN_SWEEP = [0.40, 0.45, 0.50, 0.55, 0.60]


def _gather_htf(pole_min: float, universe: list[str]):
    """HTF strateji ile gather (custom pole_min ile)."""
    from price_action.backtest.engine import BacktestEngine
    from price_action.strategies.high_tight_flag import (
        HighTightFlagStrategy,
        _default_manifest,
    )
    from scripts.run_real_backtest import _load_symbol_ohlcv

    # Custom manifest with pole_min override
    m = _default_manifest()
    for p in m.signals.patterns:
        if p.id == "htf_breakout_long":
            p.params["pole_return_min"] = pole_min

    strategy = HighTightFlagStrategy(m)

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
                # honest clip — dataset-end fantasy R'larini kapali (sec19 lesson)
                hold_d = (pd.Timestamp(t["exit_ts"]) - pd.Timestamp(t["entry_ts"])).days
                R = float(t["realized_r_multiple"])
                if hold_d > 60:
                    # likely dataset-end clip artifact (HTF runner_force_exit_bars=30)
                    R = min(R, 1.0)
                out.append({
                    "entry_ts": pd.Timestamp(t["entry_ts"]),
                    "exit_ts": pd.Timestamp(t["exit_ts"]),
                    "R": R,
                    "R_raw": float(t["realized_r_multiple"]),
                    "hold_d": hold_d,
                    "symbol": sym,
                    "side": str(t["side"]),
                })
        except Exception as exc:
            print(f"   ERROR {sym}: {exc}")
            continue
    return out


def _summary(trades, label):
    if not trades:
        return {"label": label, "n": 0, "mR": 0.0, "WR": 0.0, "max_R": 0.0,
                "median_R": 0.0, "p_shuffle": None}
    Rs = np.array([t["R"] for t in trades], dtype=float)
    Rs_raw = np.array([t["R_raw"] for t in trades], dtype=float)

    # Shuffle (sign permutation null)
    rng = np.random.default_rng(42)
    obs = float(Rs.sum())
    null_sums = []
    for _ in range(200):
        signs = rng.choice([-1, 1], size=len(Rs))
        null_sums.append((Rs * signs).sum())
    null_sums = np.array(null_sums)
    p = float((null_sums >= obs).mean())

    return {
        "label": label,
        "n": len(trades),
        "mR": float(Rs.mean()),
        "mR_raw": float(Rs_raw.mean()),
        "WR": float((Rs > 0).mean()),
        "max_R": float(Rs.max()),
        "median_R": float(np.median(Rs)),
        "sumR": float(Rs.sum()),
        "p_shuffle": p,
        "n_artifact": int((Rs_raw > 10.0).sum()),  # raw fantasy R count
        "mean_hold_d": float(np.mean([t["hold_d"] for t in trades])),
    }


def main():
    print("=" * 100)
    print("Sec22 - HTF Retest: pole_min sweep × universe (5y × 1d)")
    print("=" * 100)
    print()

    rows = []
    for pole_min in POLE_MIN_SWEEP:
        for label, univ in [("ALL_11", SYMBOLS_11), ("ALT_ONLY", ALT_ONLY)]:
            print(f"-> pole_min={pole_min:.2f}  universe={label}  (n_sym={len(univ)})")
            trades = _gather_htf(pole_min, univ)
            s = _summary(trades, f"pm={pole_min:.2f}_{label}")
            s["pole_min"] = pole_min
            s["universe"] = label
            rows.append(s)
            print(f"   n={s['n']:4d}  mR={s['mR']:+.3f}  mR_raw={s['mR_raw']:+.3f}  "
                  f"WR={s['WR']*100:.1f}%  max_R={s['max_R']:.2f}  "
                  f"p={s['p_shuffle']:.3f}  hold_d={s['mean_hold_d']:.1f}  "
                  f"artifact_n={s['n_artifact']}")

    print()
    print("=" * 100)
    print("GATE (HARD: n>=200, mR>+0.15, p<0.05, max_R<10)")
    print("=" * 100)
    print(f"{'pole_min':<10}{'universe':<12}{'n':<6}{'mR':<10}{'WR':<8}{'p':<8}{'max_R':<8}{'verdict':<12}")

    passes = []
    for s in rows:
        gate_n = s["n"] >= 200
        gate_mR = s["mR"] > 0.15
        gate_p = (s["p_shuffle"] or 1.0) < 0.05
        gate_max = s["max_R"] < 10.0
        all_ok = gate_n and gate_mR and gate_p and gate_max
        verdict = "PASS" if all_ok else "FAIL"
        fails = []
        if not gate_n: fails.append(f"n={s['n']}<200")
        if not gate_mR: fails.append(f"mR={s['mR']:.3f}<0.15")
        if not gate_p: fails.append(f"p={s['p_shuffle']:.3f}>=0.05")
        if not gate_max: fails.append(f"maxR={s['max_R']:.2f}>=10")
        info = ", ".join(fails) if fails else "ALL_OK"
        print(f"{s['pole_min']:<10}{s['universe']:<12}{s['n']:<6}{s['mR']:<10.3f}"
              f"{s['WR']*100:<8.1f}{s['p_shuffle']:<8.3f}{s['max_R']:<8.2f}{verdict:<12}{info}")
        if all_ok:
            passes.append(s)

    print()
    print(f"PASS COUNT: {len(passes)}")
    if passes:
        print("\nPASS adayları (ensemble retest için engineering slot fix sonrası):")
        for s in passes:
            print(f"  - pole_min={s['pole_min']:.2f}  universe={s['universe']}  "
                  f"n={s['n']}  mR={s['mR']:+.3f}  WR={s['WR']*100:.1f}%")

    # Save results
    import json
    out_path = ROOT / "reports" / "researcher" / "sec22_htf_retest.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w") as f:
        json.dump([{k: (None if v is None else v) for k, v in s.items()} for s in rows],
                  f, indent=2, default=str)
    print(f"\nResults saved: {out_path}")

    return rows


if __name__ == "__main__":
    main()
