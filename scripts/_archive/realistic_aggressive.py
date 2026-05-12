"""Gercekci leverage + risk officer breaker'larıyla simülasyon.

Risk %2 lev 3x baseline'ında:
- Daily DD %5 → durdur (1 gün dinlenme)
- Weekly DD %10 → durdur (5 gün dinlenme)
- Monthly DD %15 → durdur (kalan ay)
- Funding cost per 8h (~yıllık %10 lev 3x için)

Yıl-bazında karşılaştırma.
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


def replay_realistic(trades, risk_pct=0.02, leverage=3.0,
                     daily_dd=0.05, weekly_dd=0.10, monthly_dd=0.15,
                     funding_annual=0.10, max_concurrent=5):
    """Gerçekçi replay: breaker'lar + funding cost.

    Funding: lev 3x için yıllık ~%10 daily-applied. Her trade'in holding süresi
    × funding_rate × notional kadar maliyet.
    """
    if not trades:
        return {"final": 10_000.0, "trades": 0, "blocked_daily": 0, "blocked_weekly": 0, "blocked_monthly": 0, "max_dd": 0, "funding_cost": 0}

    trades = sorted(trades, key=lambda t: t["entry_ts"])
    equity = 10_000.0
    cash = 10_000.0
    open_pos = []
    n_taken = 0
    blocked_daily = 0
    blocked_weekly = 0
    blocked_monthly = 0
    total_funding = 0.0
    eq_curve = [10_000.0]

    # Anchor levels for breakers
    daily_anchor = 10_000.0
    weekly_anchor = 10_000.0
    monthly_anchor = 10_000.0
    last_day = trades[0]["entry_ts"].date()
    last_week = trades[0]["entry_ts"].isocalendar()[1]
    last_month = trades[0]["entry_ts"].month

    blocked_until = None  # block time (datetime)

    funding_per_day = funding_annual / 365

    def close_due(now):
        nonlocal cash, equity, total_funding
        still = []
        for p in open_pos:
            if p["exit_ts"] <= now:
                # Holding days for funding
                holding_days = (p["exit_ts"] - p["entry_ts"]).total_seconds() / 86400
                funding_cost = (p["margin"] * leverage) * funding_per_day * holding_days
                total_funding += funding_cost
                pnl = p["risk"] * p["R"] * leverage - funding_cost
                cash += p["margin"] + pnl
                equity = cash + sum(q["margin"] for q in still)
                eq_curve.append(equity)
            else:
                still.append(p)
        open_pos[:] = still

    for t in trades:
        close_due(t["entry_ts"])

        # Reset anchors
        cur_day = t["entry_ts"].date()
        cur_week = t["entry_ts"].isocalendar()[1]
        cur_month = t["entry_ts"].month
        if cur_day != last_day:
            daily_anchor = equity
            last_day = cur_day
        if cur_week != last_week:
            weekly_anchor = equity
            last_week = cur_week
        if cur_month != last_month:
            monthly_anchor = equity
            last_month = cur_month

        # Check breakers BEFORE opening
        daily_loss = (daily_anchor - equity) / daily_anchor if daily_anchor > 0 else 0
        weekly_loss = (weekly_anchor - equity) / weekly_anchor if weekly_anchor > 0 else 0
        monthly_loss = (monthly_anchor - equity) / monthly_anchor if monthly_anchor > 0 else 0

        if blocked_until and t["entry_ts"] < blocked_until:
            continue

        if daily_loss >= daily_dd:
            blocked_daily += 1
            blocked_until = t["entry_ts"] + timedelta(days=1)
            continue
        if weekly_loss >= weekly_dd:
            blocked_weekly += 1
            blocked_until = t["entry_ts"] + timedelta(days=7)
            continue
        if monthly_loss >= monthly_dd:
            blocked_monthly += 1
            blocked_until = t["entry_ts"] + timedelta(days=30)
            continue

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
            "margin": margin, "risk": risk_d, "R": t["R"],
        })
        n_taken += 1

    # Force close
    for p in open_pos:
        holding_days = (p["exit_ts"] - p["entry_ts"]).total_seconds() / 86400
        funding_cost = (p["margin"] * leverage) * funding_per_day * holding_days
        total_funding += funding_cost
        cash += p["margin"] + p["risk"] * p["R"] * leverage - funding_cost
        equity = cash
        eq_curve.append(equity)

    peak = eq_curve[0]
    max_dd = 0.0
    for v in eq_curve:
        if v > peak:
            peak = v
        dd = (v - peak) / peak
        if dd < max_dd:
            max_dd = dd

    return {
        "final": equity, "trades": n_taken,
        "blocked_daily": blocked_daily, "blocked_weekly": blocked_weekly, "blocked_monthly": blocked_monthly,
        "max_dd": max_dd, "funding_cost": total_funding,
    }


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

    # Risk officer'sız vs risk officer'lı karşılaştırma
    scenarios = [
        ("Risk %2 lev 2x — naked (no breaker)", 0.02, 2.0, 1.0, 1.0, 1.0, 0.10),
        ("Risk %2 lev 2x — breaker active", 0.02, 2.0, 0.05, 0.10, 0.15, 0.10),
        ("Risk %2 lev 3x — naked",         0.02, 3.0, 1.0, 1.0, 1.0, 0.10),
        ("Risk %2 lev 3x — breaker active", 0.02, 3.0, 0.05, 0.10, 0.15, 0.10),
        ("Risk %3 lev 3x — naked",         0.03, 3.0, 1.0, 1.0, 1.0, 0.10),
        ("Risk %3 lev 3x — breaker active", 0.03, 3.0, 0.05, 0.10, 0.15, 0.10),
    ]

    print(f"{'Senaryo':<40} {'Yil 1':>9} {'Yil 2':>9} {'Yil 3':>9} {'Compound':>11} {'Yillik':>9} {'maxDD':>8} {'fundCost':>10}")
    print("-" * 120)

    for label, risk_pct, lev, dd_d, dd_w, dd_m, fund in scenarios:
        eq_compound = 10_000.0
        yearly = []
        worst_dd = 0.0
        total_fund = 0.0
        total_blocked = 0
        for yr in range(3):
            ws = start + timedelta(days=365 * yr)
            we = start + timedelta(days=365 * (yr + 1))
            wt = [t for t in all_trades if ws <= t["entry_ts"] < we]
            r = replay_realistic(wt, risk_pct=risk_pct, leverage=lev, daily_dd=dd_d, weekly_dd=dd_w, monthly_dd=dd_m, funding_annual=fund)
            yr_ret = r["final"] / 10_000 - 1
            yearly.append(yr_ret)
            eq_compound *= (1 + yr_ret)
            if r["max_dd"] < worst_dd:
                worst_dd = r["max_dd"]
            total_fund += r["funding_cost"]
            total_blocked += r["blocked_daily"] + r["blocked_weekly"] + r["blocked_monthly"]
        annual = ((eq_compound / 10_000) ** (1/3) - 1) * 100
        cells = " ".join(f"{(yr*100):>+7.1f}%" for yr in yearly)
        print(f"{label:<40} {cells} ${eq_compound:>9,.0f} {annual:>+7.2f}% {worst_dd*100:>+6.1f}% ${total_fund:>8,.0f}")

    print()
    print("FUNDING NOTU: lev 2x ~%5/yıl, lev 3x ~%10/yıl. Bu rakamlar dahil.")
    print("BREAKER NOTU: daily %5 / weekly %10 / monthly %15 → tetiklenince ilgili periyot atılır.")


if __name__ == "__main__":
    main()
