"""DD optimizasyonu — DD < %30 + yıllık > %50 hedefi.

Senaryolar:
1. Sabit lev 3x risk %3 (baseline)
2. Dinamik risk: DD arttıkça size azalt
3. Vol-adjusted leverage: high-vol regime'de lev azalt
4. Kombine: dinamik risk + vol-adj leverage
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


def replay_dd_optimized(trades, mode="baseline", base_risk=0.03, base_lev=3.0,
                         daily_dd=0.05, weekly_dd=0.10, monthly_dd=0.15,
                         funding_annual=0.10, max_concurrent=5):
    """mode: baseline | dynamic_risk | vol_adjusted_lev | combined"""
    if not trades:
        return {"final": 10_000.0, "trades": 0, "max_dd": 0, "fund": 0}

    trades = sorted(trades, key=lambda t: t["entry_ts"])
    equity = 10_000.0
    cash = 10_000.0
    peak_equity = 10_000.0
    open_pos = []
    n_taken = 0
    total_funding = 0.0
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
        nonlocal cash, equity, total_funding, peak_equity
        still = []
        for p in open_pos:
            if p["exit_ts"] <= now:
                holding = (p["exit_ts"] - p["entry_ts"]).total_seconds() / 86400
                fund = p["margin"] * p["leverage"] * funding_per_day * holding
                total_funding += fund
                pnl = p["risk"] * p["R"] * p["leverage"] - fund
                cash += p["margin"] + pnl
                equity = cash + sum(q["margin"] for q in still)
                if equity > peak_equity:
                    peak_equity = equity
                eq_curve.append(equity)
            else:
                still.append(p)
        open_pos[:] = still

    for t in trades:
        close_due(t["entry_ts"])

        # Mode'a göre risk + leverage hesapla
        cur_dd = (peak_equity - equity) / peak_equity if peak_equity > 0 else 0
        # Volatility hint: SL_pct büyükse vol yüksek (proxy)
        sl_pct = abs(t["entry_price"] - t["initial_sl"]) / t["entry_price"]

        if mode == "baseline":
            risk_pct = base_risk
            leverage = base_lev
        elif mode == "dynamic_risk":
            # DD arttıkça risk azalt
            if cur_dd < 0.10:
                risk_pct = base_risk
            elif cur_dd < 0.20:
                risk_pct = base_risk * 0.66
            elif cur_dd < 0.30:
                risk_pct = base_risk * 0.33
            else:
                risk_pct = 0  # halt
            leverage = base_lev
        elif mode == "vol_adjusted_lev":
            # High-vol regime'de lev azalt (sl_pct proxy)
            if sl_pct < 0.03:
                leverage = base_lev
            elif sl_pct < 0.05:
                leverage = base_lev * 0.66
            else:
                leverage = base_lev * 0.33
            risk_pct = base_risk
        elif mode == "combined":
            if cur_dd < 0.10:
                risk_pct = base_risk
            elif cur_dd < 0.20:
                risk_pct = base_risk * 0.66
            elif cur_dd < 0.30:
                risk_pct = base_risk * 0.33
            else:
                risk_pct = 0
            if sl_pct < 0.03:
                leverage = base_lev
            elif sl_pct < 0.05:
                leverage = base_lev * 0.66
            else:
                leverage = base_lev * 0.33
        else:
            risk_pct = base_risk
            leverage = base_lev

        if risk_pct <= 0:
            continue

        # Anchor reset
        cur_day = t["entry_ts"].date()
        cur_week = t["entry_ts"].isocalendar()[1]
        cur_month = t["entry_ts"].month
        if cur_day != last_day:
            daily_anchor = equity; last_day = cur_day
        if cur_week != last_week:
            weekly_anchor = equity; last_week = cur_week
        if cur_month != last_month:
            monthly_anchor = equity; last_month = cur_month

        if blocked_until and t["entry_ts"] < blocked_until:
            continue
        daily_loss = (daily_anchor - equity) / daily_anchor if daily_anchor > 0 else 0
        weekly_loss = (weekly_anchor - equity) / weekly_anchor if weekly_anchor > 0 else 0
        monthly_loss = (monthly_anchor - equity) / monthly_anchor if monthly_anchor > 0 else 0
        if daily_loss >= daily_dd:
            blocked_until = t["entry_ts"] + timedelta(days=1); continue
        if weekly_loss >= weekly_dd:
            blocked_until = t["entry_ts"] + timedelta(days=7); continue
        if monthly_loss >= monthly_dd:
            blocked_until = t["entry_ts"] + timedelta(days=30); continue

        if len(open_pos) >= max_concurrent:
            continue
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
        total_funding += fund
        cash += p["margin"] + p["risk"] * p["R"] * p["leverage"] - fund
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

    return {"final": equity, "trades": n_taken, "max_dd": max_dd, "fund": total_funding}


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
                "R": float(t["realized_r_multiple"]),
            })
    all_trades.sort(key=lambda x: x["entry_ts"])
    print(f"Toplam {len(all_trades)} trade\n")

    if not all_trades:
        return

    start = all_trades[0]["entry_ts"]

    # Mode'lar × Risk/Lev kombinasyonları
    configs = [
        ("BASELINE — Risk %3 lev 3x", "baseline", 0.03, 3.0),
        ("DYNAMIC RISK — Risk %3 lev 3x", "dynamic_risk", 0.03, 3.0),
        ("VOL-ADJ LEV — Risk %3 lev 3x", "vol_adjusted_lev", 0.03, 3.0),
        ("COMBINED — Risk %3 lev 3x", "combined", 0.03, 3.0),
        ("BASELINE — Risk %2 lev 3x", "baseline", 0.02, 3.0),
        ("DYNAMIC RISK — Risk %2 lev 3x", "dynamic_risk", 0.02, 3.0),
        ("COMBINED — Risk %2 lev 3x", "combined", 0.02, 3.0),
        ("BASELINE — Risk %2 lev 2x", "baseline", 0.02, 2.0),
        ("DYNAMIC RISK — Risk %2 lev 2x", "dynamic_risk", 0.02, 2.0),
        ("COMBINED — Risk %2 lev 2x", "combined", 0.02, 2.0),
    ]

    print(f"{'Konfig':<40} {'Yil1':>7} {'Yil2':>7} {'Yil3':>7} {'Compound':>11} {'Yillik':>9} {'maxDD':>7} {'fund':>8}")
    print("-" * 110)

    for label, mode, risk, lev in configs:
        eq = 10_000.0
        yearly = []
        worst_dd = 0.0
        total_fund = 0.0
        for yr in range(3):
            ws = start + timedelta(days=365 * yr)
            we = start + timedelta(days=365 * (yr + 1))
            wt = [t for t in all_trades if ws <= t["entry_ts"] < we]
            r = replay_dd_optimized(wt, mode=mode, base_risk=risk, base_lev=lev)
            ret = r["final"] / 10_000 - 1
            yearly.append(ret)
            eq *= (1 + ret)
            if r["max_dd"] < worst_dd:
                worst_dd = r["max_dd"]
            total_fund += r["fund"]
        annual = ((eq / 10_000) ** (1/3) - 1) * 100
        cells = " ".join(f"{(y*100):>+5.1f}%" for y in yearly)
        print(f"{label:<40} {cells} ${eq:>9,.0f} {annual:>+7.2f}% {worst_dd*100:>+5.1f}% ${total_fund:>6,.0f}")

    print()
    print("HEDEF: yıllık > %50, maxDD < %30")
    print("Mikro-canlı uygunluğu için: hem hedef hem maxDD geçmeli")


if __name__ == "__main__":
    main()
