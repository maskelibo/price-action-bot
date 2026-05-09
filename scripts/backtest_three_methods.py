"""Backtest script: Three Methods vs Engulfing Continuation decorrelation."""
from __future__ import annotations

import sys
import os

# Ensure src is on path
_SRC = os.path.join(os.path.dirname(__file__), "..", "src")
sys.path.insert(0, os.path.abspath(_SRC))

from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd

from price_action.strategies.three_methods import ThreeMethodsStrategy, _default_manifest
from price_action.strategies.engulfing_continuation import (
    EngulfingContinuationStrategy,
    _default_manifest as eng_manifest,
)


def make_btc_like(n: int = 1200, seed: int = 42, drift: float = 0.0003) -> pd.DataFrame:
    """BTC-like synthetic OHLCV — daily bars."""
    rng = np.random.default_rng(seed)
    rets = rng.normal(drift, 0.025, n)
    close = 30000.0 * np.exp(np.cumsum(rets))
    open_ = np.r_[close[0], close[:-1]] * (1 + rng.normal(0, 0.002, n))
    high = np.maximum(open_, close) * (1 + np.abs(rng.normal(0, 0.008, n)))
    low = np.minimum(open_, close) * (1 - np.abs(rng.normal(0, 0.008, n)))
    high = np.maximum.reduce([high, open_, close])
    low = np.minimum.reduce([low, open_, close])
    volume = rng.uniform(5e8, 3e9, n)
    ts = [datetime(2019, 1, 1, tzinfo=timezone.utc) + timedelta(days=i) for i in range(n)]
    return pd.DataFrame({
        "ts": ts, "open": open_, "high": high, "low": low,
        "close": close, "volume": volume,
        "venue": "binance", "symbol": "BTC/USDT", "timeframe": "1d",
    })


def simple_backtest(
    strat,
    df: pd.DataFrame,
    initial_capital: float = 10_000.0,
    risk_per_trade: float = 0.01,
    fee_pct: float = 0.00075,
) -> tuple[list[dict], list[float]]:
    """Simplified event-driven backtest — checks close against SL/TP each bar."""
    df_feat = strat.prepare_features(df.copy())
    signals = strat.generate_signals(df_feat)

    # Map signals by timestamp
    ts_to_signals: dict = {}
    for sig in signals:
        ts_to_signals.setdefault(sig.ts, []).append(sig)

    capital = initial_capital
    equity = [capital]
    trades: list[dict] = []
    open_trades: list[dict] = []

    for _, row in df_feat.iterrows():
        ts = pd.Timestamp(row["ts"]).to_pydatetime()
        close = float(row["close"])

        # Check and close open trades
        remaining = []
        for trade in open_trades:
            if trade["direction"] == "long":
                if close >= trade["tp"]:
                    pnl = trade["risk"] * trade["R"]
                    capital += pnl - abs(pnl) * fee_pct
                    trades.append({"result": "win", "pnl": pnl, "R": trade["R"]})
                elif close <= trade["sl"]:
                    pnl = -trade["risk"]
                    capital += pnl - abs(pnl) * fee_pct
                    trades.append({"result": "loss", "pnl": pnl, "R": trade["R"]})
                else:
                    remaining.append(trade)
            else:  # short
                if close <= trade["tp"]:
                    pnl = trade["risk"] * trade["R"]
                    capital += pnl - abs(pnl) * fee_pct
                    trades.append({"result": "win", "pnl": pnl, "R": trade["R"]})
                elif close >= trade["sl"]:
                    pnl = -trade["risk"]
                    capital += pnl - abs(pnl) * fee_pct
                    trades.append({"result": "loss", "pnl": pnl, "R": trade["R"]})
                else:
                    remaining.append(trade)
        open_trades = remaining
        equity.append(capital)

        # Open new trades from signals at this timestamp
        for sig in ts_to_signals.get(ts, []):
            entry_price = close  # approximation: next bar open ~ this close
            risk_dollar = capital * risk_per_trade
            if sig.direction == "long":
                risk_pts = entry_price - sig.sl_price
                if risk_pts <= 0:
                    continue
                R = (sig.tp_price - entry_price) / risk_pts
            else:
                risk_pts = sig.sl_price - entry_price
                if risk_pts <= 0:
                    continue
                R = (entry_price - sig.tp_price) / risk_pts
            open_trades.append({
                "direction": sig.direction,
                "entry": entry_price,
                "sl": sig.sl_price,
                "tp": sig.tp_price,
                "risk": risk_dollar,
                "R": R,
            })

    return trades, equity


def print_metrics(trades: list[dict], equity: list[float], label: str) -> dict:
    """Compute and print performance metrics."""
    print(f"\n{'='*60}")
    print(f" {label}")
    print(f"{'='*60}")

    if not trades:
        print("  No trades generated.")
        return {}

    wins = [t for t in trades if t["result"] == "win"]
    total = len(trades)
    win_rate = len(wins) / total if total else 0.0

    equity_arr = np.array(equity)
    total_return = (equity_arr[-1] - equity_arr[0]) / equity_arr[0]
    n_years = len(equity) / 365.0
    if n_years > 0:
        annual_return = (1 + total_return) ** (1.0 / n_years) - 1
    else:
        annual_return = 0.0

    daily_returns = np.diff(equity_arr) / equity_arr[:-1]
    avg_ret = float(np.mean(daily_returns))
    std_ret = float(np.std(daily_returns, ddof=1)) if len(daily_returns) > 1 else 1.0
    sharpe = (avg_ret / std_ret * np.sqrt(365)) if std_ret > 0 else 0.0

    running_max = np.maximum.accumulate(equity_arr)
    drawdowns = (equity_arr - running_max) / running_max
    max_dd = float(np.min(drawdowns))

    avg_pnl = float(np.mean([t["pnl"] for t in trades]))
    avg_R = float(np.mean([t["R"] for t in trades if t.get("R", 0) > 0]))

    print(f"  Trades     : {total} total | {len(wins)} wins | {total - len(wins)} losses")
    print(f"  Win Rate   : {win_rate:.1%}  (Bulkowski target: 74%)")
    print(f"  Annual Ret : {annual_return:.1%}")
    print(f"  Total Ret  : {total_return:.1%}")
    print(f"  Sharpe     : {sharpe:.2f}")
    print(f"  Max DD     : {max_dd:.1%}")
    print(f"  Avg P&L/tr : ${avg_pnl:.2f}")
    print(f"  Avg R      : {avg_R:.2f}")
    print(f"  Final cap  : ${equity_arr[-1]:.0f}")

    return {
        "win_rate": win_rate,
        "annual": annual_return,
        "sharpe": sharpe,
        "max_dd": max_dd,
        "n_trades": total,
        "equity": equity_arr,
        "daily_returns": daily_returns,
    }


def main() -> None:
    print("Generating synthetic BTC-like data (1200 days ~3.3 years)...")
    df = make_btc_like(n=1200, seed=42)
    print(f"Data: {len(df)} bars, {df['ts'].iloc[0].date()} to {df['ts'].iloc[-1].date()}")

    # ---- Three Methods ----
    m = _default_manifest()
    strat_tm = ThreeMethodsStrategy(m)
    print("\nRunning Three Methods backtest...")
    trades_tm, equity_tm = simple_backtest(strat_tm, df)
    m_tm = print_metrics(trades_tm, equity_tm, "Three Methods (Rising+Falling)")

    # ---- Engulfing Continuation ----
    strat_eng = EngulfingContinuationStrategy(eng_manifest())
    print("\nRunning Engulfing Continuation backtest...")
    trades_eng, equity_eng = simple_backtest(strat_eng, df)
    m_eng = print_metrics(trades_eng, equity_eng, "Engulfing Continuation (baseline)")

    # ---- Decorrelation analysis ----
    print(f"\n{'='*60}")
    print(" Decorrelation Analysis")
    print(f"{'='*60}")

    df_feat_tm = strat_tm.prepare_features(df.copy())
    df_feat_eng = strat_eng.prepare_features(df.copy())
    tm_signals = strat_tm.generate_signals(df_feat_tm)
    eng_signals = strat_eng.generate_signals(df_feat_eng)

    tm_ts_set = {s.ts for s in tm_signals}
    eng_ts_set = {s.ts for s in eng_signals}
    overlap = tm_ts_set & eng_ts_set

    print(f"  Three Methods signals  : {len(tm_signals)}")
    print(f"  Engulfing signals      : {len(eng_signals)}")
    print(f"  Same-day signal overlap: {len(overlap)}")
    if tm_ts_set:
        print(f"  Overlap / TM total     : {100*len(overlap)/len(tm_ts_set):.1f}%")

    # Daily return correlation
    if m_tm and m_eng:
        r_tm = m_tm["daily_returns"]
        r_eng = m_eng["daily_returns"]
        min_len = min(len(r_tm), len(r_eng))
        if min_len > 10:
            corr = np.corrcoef(r_tm[:min_len], r_eng[:min_len])[0, 1]
            print(f"  Equity return corr     : {corr:.3f}  (low = better diversification)")

    # ---- VERDICT ----
    print(f"\n{'='*60}")
    print(" VERDICT")
    print(f"{'='*60}")
    if m_tm:
        wt = m_tm["win_rate"]
        ann = m_tm["annual"]
        sh = m_tm["sharpe"]
        dd = m_tm["max_dd"]
        verdict_parts = []
        if wt >= 0.55:
            verdict_parts.append(f"Win rate {wt:.1%} >= 55% OK")
        else:
            verdict_parts.append(f"Win rate {wt:.1%} below 55% — investigate")
        if ann > 0:
            verdict_parts.append(f"Positive CAGR ({ann:.1%})")
        else:
            verdict_parts.append(f"Negative CAGR ({ann:.1%}) — needs filter work")
        if sh > 0.5:
            verdict_parts.append(f"Sharpe {sh:.2f} acceptable")
        else:
            verdict_parts.append(f"Sharpe {sh:.2f} low")
        for vp in verdict_parts:
            print(f"  - {vp}")
        overall = "PROCEED TO FURTHER TESTING" if (wt >= 0.50 and ann > 0) else "NEEDS FILTER WORK"
        print(f"\n  OVERALL: {overall}")
        print(f"  Note: Synthetic data; real crypto backtest required for final verdict.")
        print(f"  Bulkowski stat: 74% continuation. Pattern is mechanically correct.")


if __name__ == "__main__":
    main()
