"""Sec22 RSI2 drill-down: borderline gate, parameter sensitivity + artifact forensik.

RSI2 standalone:
  - n=732 (PASS), p=0.040 (PASS), mR=+0.095 (gate altinda 0.10)
  - max_R=10.53 → 1-2 artifact trade
  - Per-symbol: 5/11 sym pozitif

Drill-down:
  - Symbol-out CV (her sembolu drop, mR stability)
  - Hold time distribution (mean-rev fast olmali?)
  - Param sensitivity: RSI thresh {5, 10, 15}, EMA {150, 200, 300}, LL/HH lookback {3, 5, 7}
  - Artifact bar inspection (max_R trade detayi)
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


def _gather_rsi2(rsi_thresh=10.0, ema_period=200, lookback=5):
    from price_action.backtest.engine import BacktestEngine
    from price_action.strategies.rsi2_extreme_fade import (
        RSI2ExtremeFadeStrategy, _default_manifest,
    )
    from scripts.run_real_backtest import _load_symbol_ohlcv

    m = _default_manifest()
    for p in m.signals.patterns:
        if p.id == "rsi2_long":
            p.params["rsi_oversold"] = rsi_thresh
            p.params["ema_trend_period"] = ema_period
            p.params["low_lookback"] = lookback
        elif p.id == "rsi2_short":
            p.params["rsi_overbought"] = 100.0 - rsi_thresh
            p.params["ema_trend_period"] = ema_period
            p.params["high_lookback"] = lookback
    strategy = RSI2ExtremeFadeStrategy(m)

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


def _stats(trades):
    if not trades:
        return None
    Rs = np.array([t["R"] for t in trades], dtype=float)
    n_long = sum(1 for t in trades if t["side"] == "long")
    n_short = sum(1 for t in trades if t["side"] == "short")
    # shuffle
    rng = np.random.default_rng(42)
    obs = float(Rs.sum())
    null_sums = []
    for _ in range(200):
        signs = rng.choice([-1, 1], size=len(Rs))
        null_sums.append((Rs * signs).sum())
    p = float((np.array(null_sums) >= obs).mean())
    return {
        "n": len(trades), "mR": float(Rs.mean()), "WR": float((Rs > 0).mean()),
        "max_R": float(Rs.max()), "median_R": float(np.median(Rs)),
        "n_long": n_long, "n_short": n_short, "p": p,
        "hold_median": float(np.median([t["hold_d"] for t in trades])),
    }


def main():
    print("=" * 100)
    print("Sec22 RSI2 DRILL-DOWN — parameter sensitivity + artifact forensik")
    print("=" * 100)
    print()

    # Default trades (baseline)
    print("[BASELINE: RSI thresh=10, EMA=200, lookback=5]")
    base = _gather_rsi2()
    s = _stats(base)
    print(f"   n={s['n']}  mR={s['mR']:+.3f}  WR={s['WR']*100:.1f}%  "
          f"p={s['p']:.3f}  max_R={s['max_R']:.2f}  median_R={s['median_R']:+.3f}  "
          f"long={s['n_long']} short={s['n_short']}  hold_med={s['hold_median']:.0f}d")
    print()

    # ARTIFACT FORENSIC: top 5 R trades
    print("[ARTIFACT INSPECTION — top 5 R trades]")
    top5 = sorted(base, key=lambda t: -t["R"])[:5]
    for t in top5:
        print(f"   {t['symbol']:<14} {t['side']:<6} R={t['R']:+.2f} (raw {t['R_raw']:+.2f})  "
              f"hold={t['hold_d']}d  entry={t['entry_ts'].date()}  exit={t['exit_ts'].date()}")
    print()

    # SYMBOL-OUT CV
    print("[SYMBOL-OUT CV — leave one out]")
    base_mR = float(np.mean([t["R"] for t in base]))
    print(f"   baseline mR={base_mR:+.3f}")
    devs = []
    for drop_sym in SYMBOLS_11:
        rem = [t for t in base if t["symbol"] != drop_sym]
        if not rem:
            continue
        sm = float(np.mean([t["R"] for t in rem]))
        dev = (sm - base_mR) / abs(base_mR) * 100 if base_mR != 0 else 0
        devs.append(dev)
        print(f"   drop {drop_sym:<14} n={len(rem):4d} mR={sm:+.3f}  dev={dev:+.1f}%")
    if devs:
        print(f"   max |dev|: {max(abs(d) for d in devs):.1f}%")
    print()

    # PARAM SENSITIVITY
    print("[PARAM SWEEP]")
    sweep = []
    for rsi_th in [5.0, 10.0, 15.0]:
        for ema_p in [150, 200, 300]:
            for lb in [3, 5, 7]:
                tr = _gather_rsi2(rsi_thresh=rsi_th, ema_period=ema_p, lookback=lb)
                if not tr:
                    continue
                ss = _stats(tr)
                sweep.append({"rsi": rsi_th, "ema": ema_p, "lb": lb, **ss})
                gate_ok = (ss["n"] >= 150 and ss["mR"] >= 0.10 and ss["WR"] >= 0.35 and
                           ss["p"] < 0.05 and ss["max_R"] < 10.0)
                ok = "PASS" if gate_ok else "fail"
                print(f"   rsi={rsi_th:>5.1f} ema={ema_p:>3d} lb={lb}  "
                      f"n={ss['n']:4d} mR={ss['mR']:+.3f} WR={ss['WR']*100:5.1f}% "
                      f"p={ss['p']:.3f} maxR={ss['max_R']:5.2f} hold={ss['hold_median']:.0f}d  [{ok}]")

    # ROBUST CONFIGS (≥2 of: mR>0.10, WR>40%, p<0.05)
    print()
    print("[ROBUST CONFIGS (mR>0.10 AND p<0.05 AND n>=150 AND maxR<10)]")
    robust = [s for s in sweep if s["mR"] >= 0.10 and s["p"] < 0.05 and s["n"] >= 150 and s["max_R"] < 10.0]
    if robust:
        print(f"   FOUND {len(robust)} configs:")
        for c in robust:
            print(f"   rsi={c['rsi']:.1f} ema={c['ema']} lb={c['lb']}  "
                  f"n={c['n']} mR={c['mR']:+.3f} WR={c['WR']*100:.1f}% p={c['p']:.3f} maxR={c['max_R']:.2f}")
    else:
        print("   None (gate strict)")

    # Save
    import json
    out_path = ROOT / "reports" / "researcher" / "sec22_rsi2_drill.json"
    with open(out_path, "w") as f:
        json.dump({"baseline": s, "sweep": sweep, "robust": robust}, f, indent=2, default=str)
    print(f"\nSaved: {out_path}")


if __name__ == "__main__":
    main()
