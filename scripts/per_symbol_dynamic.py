"""Per-symbol forward-looking dinamik konfig.

Her trade için, o sembolün geçmiş 60 bar performance'ına bakarak risk + lev ayarla.
Lookahead-yok: yalnızca trade entry zamanına kadar olan veri kullanılır.

Kurallar:
- Symbol son 60 bar Sharpe > 0.5 → risk %3 lev 3x (güçlü rejim)
- Sharpe 0.0-0.5 → risk %2 lev 2x (orta)
- Sharpe < 0.0 → risk %1 lev 1x (zayıf — küçük katıl)
- Sharpe < -0.5 → trade SKIP
"""
from __future__ import annotations

import sys
from datetime import timedelta
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))
sys.path.insert(0, str(ROOT))


SYMBOLS = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT", "XRP/USDT",
           "DOGE/USDT", "ADA/USDT", "AVAX/USDT", "LINK/USDT", "DOT/USDT"]


def _per_symbol_rolling_sharpes() -> dict[str, pd.Series]:
    """Her sembol için rolling 60-bar Sharpe series."""
    from price_action.signals.filters import rolling_sharpe
    from scripts.run_real_backtest import _load_symbol_ohlcv
    out = {}
    for sym in SYMBOLS:
        df = _load_symbol_ohlcv(sym, tf="1d")
        df = df.sort_values("ts").reset_index(drop=True)
        sharpe = rolling_sharpe(df["close"], period=60)
        # Series indexli ts (Timestamp -> sharpe)
        sharpe.index = pd.to_datetime(df["ts"], utc=True)
        out[sym] = sharpe
    return out


def replay_per_symbol_dynamic(trades, sharpe_map,
                               daily_dd=0.05, weekly_dd=0.10, monthly_dd=0.15,
                               funding_annual=0.10, max_concurrent=5):
    if not trades:
        return {"final": 10_000.0, "trades": 0, "max_dd": 0, "skip_weak": 0}

    trades = sorted(trades, key=lambda t: t["entry_ts"])
    equity = 10_000.0
    cash = 10_000.0
    open_pos = []
    n_taken = 0
    skip_weak = 0
    eq_curve = [10_000.0]

    daily_anchor = 10_000.0
    weekly_anchor = 10_000.0
    monthly_anchor = 10_000.0
    last_day = trades[0]["entry_ts"].date()
    last_week = trades[0]["entry_ts"].isocalendar()[1]
    last_month = trades[0]["entry_ts"].month
    blocked_until = None
    funding_per_day = funding_annual / 365

    def close_due(now):
        nonlocal cash, equity
        still = []
        for p in open_pos:
            if p["exit_ts"] <= now:
                holding = (p["exit_ts"] - p["entry_ts"]).total_seconds() / 86400
                fund = p["margin"] * p["leverage"] * funding_per_day * holding
                pnl = p["risk"] * p["R"] * p["leverage"] - fund
                cash += p["margin"] + pnl
                equity = cash + sum(q["margin"] for q in still)
                eq_curve.append(equity)
            else:
                still.append(p)
        open_pos[:] = still

    for t in trades:
        close_due(t["entry_ts"])

        # Find rolling Sharpe at entry_ts (sembol-specific, lookahead-free)
        sym = t["symbol"]
        ssharpe = sharpe_map.get(sym)
        cur_sharpe = 0
        if ssharpe is not None:
            # Convert entry_ts to UTC tz-aware for index match
            ts = pd.Timestamp(t["entry_ts"]).tz_convert("UTC") if pd.Timestamp(t["entry_ts"]).tzinfo else pd.Timestamp(t["entry_ts"], tz="UTC")
            # Take last available value strictly BEFORE entry_ts
            valid = ssharpe[ssharpe.index < ts]
            if len(valid) > 0:
                cur_sharpe = float(valid.iloc[-1])

        # Tier'a göre risk + lev
        if cur_sharpe < -0.5:
            skip_weak += 1
            continue
        elif cur_sharpe < 0.0:
            risk_pct = 0.01; leverage = 1.0
        elif cur_sharpe < 0.5:
            risk_pct = 0.02; leverage = 2.0
        else:
            risk_pct = 0.03; leverage = 3.0

        # Anchor reset
        cur_day = t["entry_ts"].date()
        cur_week = t["entry_ts"].isocalendar()[1]
        cur_month = t["entry_ts"].month
        if cur_day != last_day: daily_anchor = equity; last_day = cur_day
        if cur_week != last_week: weekly_anchor = equity; last_week = cur_week
        if cur_month != last_month: monthly_anchor = equity; last_month = cur_month

        if blocked_until and t["entry_ts"] < blocked_until:
            continue
        if (daily_anchor - equity) / max(daily_anchor, 1) >= daily_dd:
            blocked_until = t["entry_ts"] + timedelta(days=1); continue
        if (weekly_anchor - equity) / max(weekly_anchor, 1) >= weekly_dd:
            blocked_until = t["entry_ts"] + timedelta(days=7); continue
        if (monthly_anchor - equity) / max(monthly_anchor, 1) >= monthly_dd:
            blocked_until = t["entry_ts"] + timedelta(days=30); continue

        if len(open_pos) >= max_concurrent:
            continue
        sl_pct = abs(t["entry_price"] - t["initial_sl"]) / t["entry_price"]
        if sl_pct <= 0:
            continue
        risk_d = equity * risk_pct
        notional = risk_d / sl_pct
        margin = notional / leverage
        if margin > cash:
            continue
        cash -= margin
        open_pos.append({
            "entry_ts": t["entry_ts"], "exit_ts": t["exit_ts"],
            "margin": margin, "risk": risk_d, "R": t["R"], "leverage": leverage,
        })
        n_taken += 1

    for p in open_pos:
        holding = (p["exit_ts"] - p["entry_ts"]).total_seconds() / 86400
        fund = p["margin"] * p["leverage"] * funding_per_day * holding
        cash += p["margin"] + p["risk"] * p["R"] * p["leverage"] - fund
        equity = cash
        eq_curve.append(equity)

    peak = eq_curve[0]
    max_dd = 0
    for v in eq_curve:
        if v > peak: peak = v
        dd = (v - peak) / peak
        if dd < max_dd: max_dd = dd

    return {"final": equity, "trades": n_taken, "max_dd": max_dd, "skip_weak": skip_weak}


def main():
    from price_action.backtest.engine import BacktestEngine
    from price_action.strategies.engulfing_continuation import (
        EngulfingContinuationStrategy, _default_manifest as engulf_manifest,
    )
    from scripts.run_real_backtest import _load_symbol_ohlcv

    print("Trade'leri topluyor...")
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
    print(f"Toplam {len(all_trades)} trade")

    print("\nRolling 60-bar Sharpe hesaplanıyor (per-symbol, lookahead-yok)...")
    sharpe_map = _per_symbol_rolling_sharpes()
    print(f"  {len(sharpe_map)} sembol Sharpe map'e alındı\n")

    if not all_trades:
        return

    start = all_trades[0]["entry_ts"]
    print(f"{'Konfig':<35} {'Yil1':>7} {'Yil2':>7} {'Yil3':>7} {'Compound':>11} {'Yillik':>9} {'maxDD':>7} {'açılan':>7} {'skipW':>6}")
    print("-" * 110)

    eq_compound = 10_000.0
    yearly = []
    worst_dd = 0.0
    total_taken = 0
    total_skip = 0
    for yr in range(3):
        ws = start + timedelta(days=365 * yr)
        we = start + timedelta(days=365 * (yr + 1))
        wt = [t for t in all_trades if ws <= t["entry_ts"] < we]
        r = replay_per_symbol_dynamic(wt, sharpe_map)
        ret = r["final"] / 10_000 - 1
        yearly.append(ret)
        eq_compound *= (1 + ret)
        if r["max_dd"] < worst_dd:
            worst_dd = r["max_dd"]
        total_taken += r["trades"]
        total_skip += r["skip_weak"]
    annual = ((eq_compound / 10_000) ** (1/3) - 1) * 100
    cells = " ".join(f"{(y*100):>+5.1f}%" for y in yearly)
    print(f"{'PER-SYMBOL DYNAMIC':<35} {cells} ${eq_compound:>9,.0f} {annual:>+7.2f}% {worst_dd*100:>+5.1f}% {total_taken:>7} {total_skip:>6}")
    print()
    print("HEDEF: yıllık > %50, maxDD < %30")
    if annual > 50 and abs(worst_dd) * 100 < 30:
        print("✅ HEDEFE ULASILDI — Mikro-canlı uygun")
    else:
        print(f"❌ Hedef geçilmedi — yıllık {annual:.1f}% / DD {worst_dd*100:.1f}%")


if __name__ == "__main__":
    main()
