"""HTF Momentum standalone backtest — Researcher Sprint 2026-05-14.

Pre-registered: memory/researcher/hypotheses/2026-05-12-htf-momentum-mtf-confluence.md

Hizli gate test:
  - 11 sembol 5y 1d backtest
  - Standalone yillik > %10 (hard floor)
  - 3y window (2023-01-01 → 2026-05-12) yillik
  - Trade sayisi 20-100/yil bekleniyor
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import logging
logging.getLogger("price_action").setLevel(logging.WARNING)
import os
os.environ["LOG_LEVEL"] = "WARNING"

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))
sys.path.insert(0, str(ROOT))

SYMBOLS_11 = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT",
              "ADA/USDT", "AVAX/USDT", "LINK/USDT", "DOT/USDT",
              "DOGE/USDT", "XRP/USDT", "MATIC/USDT"]


def main():
    t0 = time.time()
    print("=" * 80)
    print("HTF Momentum Standalone Backtest")
    print("=" * 80)
    print(f"Pre-registered: memory/researcher/hypotheses/2026-05-12-htf-momentum-mtf-confluence.md")

    from price_action.backtest.engine import BacktestEngine
    from price_action.signals.filters import volume_zscore
    from price_action.strategies.htf_momentum import (
        HTFMomentumStrategy, _default_manifest,
    )
    from scripts.run_real_backtest import _load_symbol_ohlcv

    s = HTFMomentumStrategy(_default_manifest())

    all_trades = []
    for sym in SYMBOLS_11:
        df = _load_symbol_ohlcv(sym, tf="1d")
        if df is None or df.empty:
            print(f"  {sym:<12} no data")
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

        e = BacktestEngine(risk_officer=None, store_load=None)
        r = e.run(
            s, [sym],
            start=df["ts"].iloc[0].to_pydatetime(),
            end=df["ts"].iloc[-1].to_pydatetime(),
            timeframe="1d",
            initial_capital=10_000.0,
            fees={"taker": 0.00075, "maker": -0.00010},
            slippage_bps=5.0,
            ohlcv_provider=prov,
        )
        for _, t in r.trades.iterrows():
            ts_e = pd.Timestamp(t["entry_ts"])
            if ts_e.tzinfo is None:
                ts_e = ts_e.tz_localize("UTC")
            ts_x = pd.Timestamp(t["exit_ts"])
            if ts_x.tzinfo is None:
                ts_x = ts_x.tz_localize("UTC")
            all_trades.append({
                "entry_ts": ts_e,
                "exit_ts": ts_x,
                "symbol": sym,
                "side": t["side"],
                "strategy": "htf_momentum",
                "R": float(t["realized_r_multiple"]),
                "conf": float(t.get("confluence_score", 1.5)),
                "entry_price": float(t["entry_price"]),
                "initial_sl": float(t["initial_sl"]),
            })
        print(f"  {sym:<12} {len([x for x in all_trades if x['symbol']==sym])} trades (cumul {len(all_trades)})")

    print(f"\nToplam trade pool (5y): {len(all_trades)}")

    if not all_trades:
        print("HATA: hicbir trade uretilmedi — strateji cok kisitlayici olabilir.")
        print(f"Elapsed: {time.time() - t0:.1f}s")
        return 1

    # 3y window (2023-01-01 -> 2026-05-12)
    cutoff = pd.Timestamp("2023-01-01", tz="UTC")
    end_cut = pd.Timestamp("2026-05-13", tz="UTC")
    trades_3y = [t for t in all_trades if cutoff <= t["entry_ts"] < end_cut]
    print(f"3y window trade sayisi: {len(trades_3y)}")

    # Sirala
    trades_3y.sort(key=lambda x: x["entry_ts"])

    # Simple replay — flat %2 risk + 2x lev (T2 baseline)
    equity = 10_000.0
    cash = 10_000.0
    open_pos = []
    eq_curve = [10_000.0]
    Rs = []

    from datetime import timedelta
    last_entry = {}
    cooldown_days = 3

    for t in trades_3y:
        # close due
        still = []
        for p in open_pos:
            if p["exit_ts"] <= t["entry_ts"]:
                pnl = p["risk"] * p["R"]
                cash += p["margin"] + pnl
                equity = cash + sum(q["margin"] for q in still)
                Rs.append(p["R"])
                eq_curve.append(equity)
            else:
                still.append(p)
        open_pos = still

        # cooldown
        key = (t["symbol"], t["side"])
        prev = last_entry.get(key)
        if prev is not None and (t["entry_ts"] - prev).days < cooldown_days:
            continue
        if len(open_pos) >= 8:
            continue

        sl_pct = abs(t["entry_price"] - t["initial_sl"]) / t["entry_price"]
        if sl_pct <= 0:
            continue

        # Flat T2: 2% risk, 2x lev
        risk_d = equity * 0.02
        notional = risk_d / sl_pct
        max_notional = equity * 0.30
        if notional > max_notional:
            notional = max_notional
            risk_d = notional * sl_pct
        margin = notional / 2.0
        if margin > cash:
            continue
        cash -= margin
        last_entry[key] = t["entry_ts"]
        open_pos.append({"exit_ts": t["exit_ts"], "margin": margin, "risk": risk_d, "R": t["R"]})

    # close remaining
    for p in open_pos:
        cash += p["margin"] + p["risk"] * p["R"]
        equity = cash
        Rs.append(p["R"])
        eq_curve.append(equity)

    if not Rs:
        print("HATA: replay icinde trade kalmadi.")
        return 1

    final_eq = equity
    total_ret = (final_eq / 10_000.0 - 1) * 100
    years = (end_cut - cutoff).total_seconds() / (365.25 * 86400)
    annual = ((final_eq / 10_000.0) ** (1 / years) - 1) * 100 if final_eq > 0 else -100

    peak = eq_curve[0]
    max_dd = 0.0
    for v in eq_curve:
        if v > peak: peak = v
        dd = (v - peak) / peak
        if dd < max_dd: max_dd = dd

    wr = sum(1 for x in Rs if x > 0) / len(Rs)
    avg_r = float(np.mean(Rs))
    print()
    print("STANDALONE BACKTEST RESULTS (3y, 2023-01 → 2026-05):")
    print(f"  Final equity: ${final_eq:.2f}")
    print(f"  Total return: {total_ret:+.2f}%")
    print(f"  Annual return (CAGR): {annual:+.2f}%/yr")
    print(f"  Max DD: {max_dd*100:.2f}%")
    print(f"  Trades: {len(Rs)} ({len(Rs)/years:.1f}/yr)")
    print(f"  Win rate: {wr*100:.1f}%")
    print(f"  Avg R: {avg_r:+.3f}")

    # Sembol/side dagilim
    by_sym = {}
    for t in trades_3y:
        by_sym.setdefault(t["symbol"], 0)
        by_sym[t["symbol"]] += 1
    print(f"\nTrade dagilim:")
    for sym, n in sorted(by_sym.items(), key=lambda x: -x[1]):
        print(f"  {sym:<12} {n}")

    # Gate kontrolu
    print()
    print("Pre-registered gate'ler (Researcher B):")
    standalone_gate = annual >= 10.0
    dd_gate = max_dd >= -0.45
    print(f"  [{'PASS' if standalone_gate else 'FAIL'}] Standalone yillik >= %10:  actual={annual:+.2f}%")
    print(f"  [{'PASS' if dd_gate else 'FAIL'}] Max DD >= -45%:             actual={max_dd*100:.2f}%")
    print(f"  Hedef trade frekansi 30-100/yr: actual={len(Rs)/years:.1f}/yr")

    print(f"\nElapsed: {time.time() - t0:.1f}s")

    # Cache trades for combine test
    import pickle
    cache_path = ROOT / "data" / "htf_momentum_trades.pkl"
    with open(cache_path, "wb") as f:
        pickle.dump(all_trades, f)
    print(f"Trades cached: {cache_path}")

    return 0 if standalone_gate else 1


if __name__ == "__main__":
    sys.exit(main())
