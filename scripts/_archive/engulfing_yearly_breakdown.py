"""Engulfing strategy yıl-bazında breakdown.

3 yılı 3 ayrı 1-yıllık pencereye böl. Her pencere için:
- Tek $10K hesap
- 5 max concurrent
- Engulfing strategy
- Final equity, getiri %, win rate, Sharpe
"""
from __future__ import annotations

import math
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))
sys.path.insert(0, str(ROOT))


SYMBOLS = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT", "XRP/USDT",
           "DOGE/USDT", "ADA/USDT", "AVAX/USDT", "LINK/USDT", "DOT/USDT"]


def replay_window(trades, year_label):
    if not trades:
        return {"year": year_label, "trades": 0, "final": 10_000.0, "ret": 0.0, "sharpe": 0, "win": 0, "max_dd": 0}

    trades = sorted(trades, key=lambda t: t["entry_ts"])
    equity = 10_000.0
    cash = 10_000.0
    open_pos = []
    n_taken = 0
    Rs = []
    eq_curve = [10_000.0]

    for t in trades:
        # Close due
        still = []
        for p in open_pos:
            if p["exit_ts"] <= t["entry_ts"]:
                pnl = p["risk"] * p["R"]
                cash += p["notional"] + pnl
                equity = cash + sum(q["notional"] for q in still)
                Rs.append(p["R"])
                eq_curve.append(equity)
            else:
                still.append(p)
        open_pos = still
        if len(open_pos) >= 5:
            continue
        sl_pct = abs(t["entry_price"] - t["initial_sl"]) / t["entry_price"]
        if sl_pct <= 0:
            continue
        risk_d = equity * 0.01
        notional = risk_d / sl_pct
        if notional > cash:
            continue
        cash -= notional
        open_pos.append({"exit_ts": t["exit_ts"], "notional": notional, "risk": risk_d, "R": t["R"]})
        n_taken += 1

    # Force close
    for p in open_pos:
        cash += p["notional"] + p["risk"] * p["R"]
        equity = cash
        Rs.append(p["R"])
        eq_curve.append(equity)

    ret = (equity / 10_000) - 1
    win = sum(1 for x in Rs if x > 0) / len(Rs) if Rs else 0
    # Per-trade Sharpe approximation
    if len(Rs) > 1:
        mean_r = sum(Rs) / len(Rs)
        std_r = (sum((x - mean_r) ** 2 for x in Rs) / len(Rs)) ** 0.5
        sharpe_per = (mean_r / std_r) if std_r > 0 else 0
    else:
        sharpe_per = 0
    # MaxDD
    peak = eq_curve[0]
    max_dd = 0
    for v in eq_curve:
        if v > peak:
            peak = v
        dd = (v - peak) / peak
        if dd < max_dd:
            max_dd = dd

    return {"year": year_label, "trades": n_taken, "final": equity, "ret": ret,
            "sharpe": sharpe_per, "win": win, "max_dd": max_dd}


def main():
    from price_action.backtest.engine import BacktestEngine
    from price_action.strategies.engulfing_continuation import (
        EngulfingContinuationStrategy, _default_manifest as engulf_manifest,
    )
    from scripts.run_real_backtest import _load_symbol_ohlcv

    print("Tüm engulfing trade'lerini topluyor...")
    manifest = engulf_manifest()
    all_trades = []
    for sym in SYMBOLS:
        df = _load_symbol_ohlcv(sym, tf="1d")
        s = EngulfingContinuationStrategy(manifest)
        df_feats = s.prepare_features(df)
        def prov(*a, **k): return df_feats.copy()
        e = BacktestEngine(risk_officer=None, store_load=None)
        r = e.run(s, [sym], start=df["ts"].iloc[0].to_pydatetime(), end=df["ts"].iloc[-1].to_pydatetime(), timeframe="1d", initial_capital=10_000.0, fees={"taker":0.00075,"maker":-0.00010}, slippage_bps=5.0, ohlcv_provider=prov)
        for _, t in r.trades.iterrows():
            all_trades.append({
                "entry_ts": t["entry_ts"], "exit_ts": t["exit_ts"],
                "entry_price": float(t["entry_price"]), "initial_sl": float(t["initial_sl"]),
                "R": float(t["realized_r_multiple"]), "symbol": sym,
            })
    all_trades.sort(key=lambda x: x["entry_ts"])
    print(f"Toplam: {len(all_trades)} trade\n")

    # 3 yıllık pencere
    if not all_trades:
        return
    start = all_trades[0]["entry_ts"]
    end = all_trades[-1]["exit_ts"]
    print(f"Veri: {start.date()} -> {end.date()}\n")

    # Each year window
    windows = []
    for yr in range(3):
        win_start = start + timedelta(days=365 * yr)
        win_end = start + timedelta(days=365 * (yr + 1))
        win_trades = [t for t in all_trades if win_start <= t["entry_ts"] < win_end]
        label = f"Yil {yr+1} ({win_start.date()} → {win_end.date()})"
        windows.append((label, win_trades))

    # Replay each
    print(f"{'Yil':<35} {'trade':>6} {'final$':>10} {'getiri':>8} {'win%':>6} {'avgR':>7} {'maxDD':>7}")
    print("-" * 90)
    rets = []
    for label, trades in windows:
        r = replay_window(trades, label)
        rets.append(r["ret"])
        print(f"{label:<35} {r['trades']:>6} {r['final']:>10,.0f} {r['ret']*100:>+7.2f}% {r['win']*100:>5.1f}% {r['sharpe']:>+7.2f} {r['max_dd']*100:>+6.1f}%")

    # 6 aylık alternatif breakdown
    print(f"\n--- 6 AYLIK PERIYOTLAR ---")
    print(f"{'Donem':<35} {'trade':>6} {'final$':>10} {'getiri':>8} {'win%':>6} {'avgR':>7}")
    print("-" * 90)
    for half in range(6):
        win_start = start + timedelta(days=183 * half)
        win_end = start + timedelta(days=183 * (half + 1))
        win_trades = [t for t in all_trades if win_start <= t["entry_ts"] < win_end]
        label = f"6ay {half+1} ({win_start.date()} → {win_end.date()})"
        r = replay_window(win_trades, label)
        print(f"{label:<35} {r['trades']:>6} {r['final']:>10,.0f} {r['ret']*100:>+7.2f}% {r['win']*100:>5.1f}% {r['sharpe']:>+7.2f}")

    # Compounded annual
    print(f"\n--- COMPOUNDING ZINCIRI ---")
    eq = 10_000.0
    print(f"Baslangic: ${eq:,.0f}")
    for label, trades in windows:
        r = replay_window([{**t, "entry_ts": t["entry_ts"]} for t in trades], label)
        # Apply yearly return
        eq *= (1 + r["ret"])
        print(f"  {label}: {r['ret']*100:+.2f}% → ${eq:,.0f}")
    annual = ((eq / 10_000) ** (1/3) - 1) * 100
    print(f"\n3y compound: ${eq:,.0f} (+{(eq/10_000-1)*100:.2f}%)")
    print(f"Yıllık ortalama: {annual:+.2f}%")

    # En iyi yıl + en kötü yıl
    best = max(rets)
    worst = min(rets)
    print(f"\nEn iyi yıl: {best*100:+.2f}%")
    print(f"En kötü yıl: {worst*100:+.2f}%")
    print(f"Yıllar arası volatilite (σ): {(sum((x-sum(rets)/3)**2 for x in rets)/3)**0.5*100:.2f}%")


if __name__ == "__main__":
    main()
