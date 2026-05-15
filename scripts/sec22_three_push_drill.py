"""Sec22 three_push_wedge_fade RELAX TEST — n=10 yetersiz, parametre rahatlatma deneyi.

Default: marginal_gain in [0.005, 0.05], wedge convergence rising lows, body<0.40, wick>0.40

Test:
  - marginal_gain {0.003-0.08, 0.005-0.10, 0.01-0.15}
  - body_max {0.40, 0.50, 0.60}
  - wick_min {0.30, 0.40, 0.50}
  - wedge convergence ON/OFF (relax)
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


def _gather(mg_min, mg_max, body_max, wick_min):
    from price_action.backtest.engine import BacktestEngine
    from price_action.strategies.three_push_wedge_fade import (
        ThreePushWedgeFadeStrategy, _default_manifest,
    )
    from scripts.run_real_backtest import _load_symbol_ohlcv

    m = _default_manifest()
    for p in m.signals.patterns:
        p.params["marginal_gain_min"] = mg_min
        p.params["marginal_gain_max"] = mg_max
        p.params["body_ratio_max"] = body_max
        p.params["wick_ratio_min"] = wick_min
    strategy = ThreePushWedgeFadeStrategy(m)

    out = []
    for sym in SYMBOLS_11:
        try:
            df = _load_symbol_ohlcv(sym, tf="1d")
            if df is None or df.empty:
                continue
            df = df.sort_values("ts").reset_index(drop=True)
            df["symbol"] = sym; df["venue"] = "binance"; df["timeframe"] = "1d"

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
                hold_d = (pd.Timestamp(t["exit_ts"]) - pd.Timestamp(t["entry_ts"])).days
                R_raw = float(t["realized_r_multiple"])
                R = R_raw if hold_d <= 60 else min(R_raw, 1.0)
                out.append({"R": R, "R_raw": R_raw, "hold_d": hold_d, "symbol": sym, "side": str(t["side"])})
        except Exception:
            continue
    return out


def _stats(trades):
    if not trades:
        return {"n": 0}
    Rs = np.array([t["R"] for t in trades], dtype=float)
    rng = np.random.default_rng(42)
    obs = float(Rs.sum())
    null = np.array([(Rs * rng.choice([-1, 1], size=len(Rs))).sum() for _ in range(200)])
    p = float((null >= obs).mean())
    return {"n": len(trades), "mR": float(Rs.mean()), "WR": float((Rs > 0).mean()),
            "max_R": float(Rs.max()), "p": p}


def main():
    print("Sec22 - three_push_wedge_fade RELAX TEST")
    print("=" * 80)
    print()
    # Sweep
    configs = []
    for mg_min, mg_max in [(0.003, 0.06), (0.005, 0.05), (0.005, 0.08), (0.005, 0.12), (0.01, 0.15)]:
        for body in [0.40, 0.50, 0.60]:
            for wick in [0.30, 0.40, 0.50]:
                trades = _gather(mg_min, mg_max, body, wick)
                s = _stats(trades)
                gate = (s.get("n", 0) >= 150 and s.get("mR", 0) >= 0.10 and
                        s.get("WR", 0) >= 0.35 and s.get("p", 1) < 0.05 and s.get("max_R", 99) < 10)
                tag = "PASS" if gate else ""
                if s["n"] > 0:
                    print(f"   mg=[{mg_min:.3f},{mg_max:.2f}] body<{body:.2f} wick>{wick:.2f}  "
                          f"n={s['n']:4d} mR={s.get('mR', 0):+.3f} WR={s.get('WR', 0)*100:5.1f}% "
                          f"p={s.get('p', 1):.3f} maxR={s.get('max_R', 0):5.2f}  {tag}")
                else:
                    print(f"   mg=[{mg_min:.3f},{mg_max:.2f}] body<{body:.2f} wick>{wick:.2f}  n=0")

if __name__ == "__main__":
    main()
