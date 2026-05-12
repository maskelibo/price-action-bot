"""Hedef %50-60 yıllık için agresif senaryolar.

Engulfing'in 166 trade'ini 1-yıllık 3 pencerede aşağıdaki senaryolarla replay et:
- Risk %1, leverage 1x (baseline)
- Risk %2, leverage 1x
- Risk %3, leverage 1x
- Risk %1, leverage 2x (perp)
- Risk %1, leverage 3x (perp)
- Risk %2, leverage 2x
- Risk %3, leverage 3x (agresif)
"""
from __future__ import annotations

import sys
from datetime import timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))
sys.path.insert(0, str(ROOT))


SYMBOLS = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT", "XRP/USDT",
           "DOGE/USDT", "ADA/USDT", "AVAX/USDT", "LINK/USDT", "DOT/USDT"]


def replay(trades, risk_pct=0.01, leverage=1.0, max_concurrent=5):
    """Replay with parametric risk and leverage.

    Leverage: notional çarpanı. Risk dollars sabit, ama açılan notional × leverage.
    R-multiple realize edilen getiri orijinal sample'dan; leverage uygulanır.
    Cash kontrolü: leverage'lı trade'de cash'in margin kısmı bağlanır.
    """
    if not trades:
        return {"final": 10_000.0, "trades": 0, "skip_cash": 0, "max_dd": 0}

    trades = sorted(trades, key=lambda t: t["entry_ts"])
    equity = 10_000.0
    cash = 10_000.0
    open_pos = []
    n_taken = 0
    n_skip_cash = 0
    eq_curve = [10_000.0]

    def close_due(now):
        nonlocal cash, equity
        still = []
        for p in open_pos:
            if p["exit_ts"] <= now:
                # PnL with leverage: R × risk_dollars × leverage
                pnl = p["risk"] * p["R"] * p["leverage"]
                cash += p["margin"] + pnl
                equity = cash + sum(q["margin"] for q in still)
                eq_curve.append(equity)
            else:
                still.append(p)
        open_pos[:] = still

    for t in trades:
        close_due(t["entry_ts"])
        if len(open_pos) >= max_concurrent:
            continue
        sl_pct = abs(t["entry_price"] - t["initial_sl"]) / t["entry_price"]
        if sl_pct <= 0:
            continue
        risk_d = equity * risk_pct
        notional = risk_d / sl_pct
        # Leverage: margin = notional / leverage (cash bound)
        margin = notional / leverage
        if margin > cash:
            n_skip_cash += 1
            continue
        cash -= margin
        open_pos.append({
            "exit_ts": t["exit_ts"], "margin": margin, "risk": risk_d,
            "R": t["R"], "leverage": leverage,
        })
        n_taken += 1

    # Force close
    for p in open_pos:
        cash += p["margin"] + p["risk"] * p["R"] * p["leverage"]
        equity = cash
        eq_curve.append(equity)

    # MaxDD
    peak = eq_curve[0]
    max_dd = 0.0
    for v in eq_curve:
        if v > peak:
            peak = v
        dd = (v - peak) / peak
        if dd < max_dd:
            max_dd = dd

    return {"final": equity, "trades": n_taken, "skip_cash": n_skip_cash, "max_dd": max_dd}


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
                "R": float(t["realized_r_multiple"]),
            })
    all_trades.sort(key=lambda x: x["entry_ts"])
    print(f"Toplam {len(all_trades)} trade\n")

    if not all_trades:
        return

    start = all_trades[0]["entry_ts"]
    scenarios = [
        ("Risk %1, lev 1x (BASELINE)", 0.01, 1.0),
        ("Risk %2, lev 1x", 0.02, 1.0),
        ("Risk %3, lev 1x", 0.03, 1.0),
        ("Risk %1, lev 2x (perp)", 0.01, 2.0),
        ("Risk %1, lev 3x (perp)", 0.01, 3.0),
        ("Risk %2, lev 2x", 0.02, 2.0),
        ("Risk %2, lev 3x", 0.02, 3.0),
        ("Risk %3, lev 3x (agresif)", 0.03, 3.0),
    ]

    print(f"{'Senaryo':<32} {'Yil 1':>10} {'Yil 2':>10} {'Yil 3':>10} {'3y compound':>14} {'Yillik':>9} {'maxDD':>8}")
    print("-" * 110)

    for label, risk_pct, lev in scenarios:
        eq_compound = 10_000.0
        yearly = []
        worst_dd = 0.0
        for yr in range(3):
            ws = start + timedelta(days=365 * yr)
            we = start + timedelta(days=365 * (yr + 1))
            wt = [t for t in all_trades if ws <= t["entry_ts"] < we]
            r = replay(wt, risk_pct=risk_pct, leverage=lev, max_concurrent=5)
            yr_ret = r["final"] / 10_000 - 1
            yearly.append(yr_ret)
            eq_compound *= (1 + yr_ret)
            if r["max_dd"] < worst_dd:
                worst_dd = r["max_dd"]
        annual = ((eq_compound / 10_000) ** (1/3) - 1) * 100
        cells = " ".join(f"{(yr*100):>+8.1f}%" for yr in yearly)
        print(f"{label:<32} {cells} ${eq_compound:>11,.0f} {annual:>+7.2f}% {worst_dd*100:>+6.1f}%")


if __name__ == "__main__":
    main()
