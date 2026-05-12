"""DD-azaltma optimizasyon sweep'i.

Hedef: yıllık %50+ + DD %30 altı + tutarlılık (yıllar arası σ < %30)
Production A baseline: yıllık %68, DD %65, σ %60

Test edilen yaklaşımlar:
1. Baseline (mevcut Production A): R%2 lev 1-5x, breaker 5/10/15
2. Risk azalt: R%1.5
3. Risk azalt: R%1 (en defansif)
4. Max concurrent 3 (kapital concentration düşür)
5. Sıkı breaker: daily 3% / weekly 7% / monthly 12%
6. Recovery mode: DD bands → lev cap (DD %20+ lev cap 2, DD %30+ halt)
7. Vol-scaling: high ATR günlerinde lev 1x cap
8. Combined defensive: R%1.5 + concurrent 3 + sıkı breaker
9. Combined moderate: R%1.5 + recovery mode
"""
from __future__ import annotations

import sys
from datetime import timedelta
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))
sys.path.insert(0, str(ROOT))


SYMBOLS = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT", "XRP/USDT",
           "DOGE/USDT", "ADA/USDT", "AVAX/USDT", "LINK/USDT", "DOT/USDT"]


def _gather_engulfing():
    from price_action.backtest.engine import BacktestEngine
    from price_action.strategies.engulfing_continuation import (
        EngulfingContinuationStrategy, _default_manifest as engulf_manifest,
    )
    from price_action.signals.filters import rolling_sharpe
    from scripts.run_real_backtest import _load_symbol_ohlcv

    manifest = engulf_manifest()
    out = []
    for sym in SYMBOLS:
        df = _load_symbol_ohlcv(sym, tf="1d")
        df = df.sort_values("ts").reset_index(drop=True)
        s = EngulfingContinuationStrategy(manifest)
        df_feats = s.prepare_features(df)
        df_feats["rolling_sharpe_60"] = rolling_sharpe(df_feats["close"], period=60)
        df_feats["body_ratio"] = (df_feats["close"] - df_feats["open"]).abs() / (df_feats["high"] - df_feats["low"]).replace(0, np.nan)
        ts_map = pd.to_datetime(df_feats["ts"], utc=True)
        def prov(*a, **k): return df_feats.copy()
        e = BacktestEngine(risk_officer=None, store_load=None)
        r = e.run(s, [sym], start=df["ts"].iloc[0].to_pydatetime(), end=df["ts"].iloc[-1].to_pydatetime(), timeframe="1d", initial_capital=10_000.0, fees={"taker":0.00075,"maker":-0.00010}, slippage_bps=5.0, ohlcv_provider=prov)
        for _, t in r.trades.iterrows():
            ts = pd.Timestamp(t["entry_ts"])
            if ts.tzinfo is None: ts = ts.tz_localize("UTC")
            mask = ts_map < ts
            if not mask.any(): continue
            idx = ts_map[mask].index[-1]
            er = float(df_feats["kaufman_er"].iloc[idx]) if "kaufman_er" in df_feats else 0
            atr_pct = float(df_feats["atr_pct"].iloc[idx]) if "atr_pct" in df_feats else 0
            rs60 = float(df_feats["rolling_sharpe_60"].iloc[idx])
            body = float(df_feats["body_ratio"].iloc[idx])
            if np.isnan(rs60): rs60 = 0
            if np.isnan(body): body = 0
            if np.isnan(atr_pct): atr_pct = 0
            cn = max(0.0, min(1.0, (float(t["confluence_score"]) - 1.5) / 1.5))
            en = max(0.0, min(1.0, er))
            rn = max(0.0, min(1.0, (rs60 + 1.0) / 2.0))
            bn = max(0.0, min(1.0, body))
            conf = 0.35 * cn + 0.25 * en + 0.25 * rn + 0.15 * bn
            if conf < 0.32: lev = 1.0
            elif conf < 0.42: lev = 2.0
            elif conf < 0.52: lev = 3.0
            elif conf < 0.58: lev = 4.0
            else: lev = 5.0
            out.append({
                "entry_ts": t["entry_ts"], "exit_ts": t["exit_ts"],
                "entry_price": float(t["entry_price"]), "initial_sl": float(t["initial_sl"]),
                "R": float(t["realized_r_multiple"]), "symbol": sym,
                "conf": conf, "lev": lev, "atr_pct": atr_pct,
            })
    out.sort(key=lambda x: x["entry_ts"])
    return out


def replay(trades, risk_pct=0.02, max_concurrent=5, daily_dd=0.05, weekly_dd=0.10, monthly_dd=0.15,
           fund_annual=0.10, recovery_mode=False, vol_scaling=False):
    """Configurable replay with multiple DD-reduction modes."""
    if not trades:
        return None
    trades = sorted(trades, key=lambda t: t["entry_ts"])
    equity = 10_000.0
    cash = 10_000.0
    peak_equity = 10_000.0
    open_pos = []
    eq_curve = [10_000.0]
    fund_d = fund_annual / 365

    daily_anchor = weekly_anchor = monthly_anchor = 10_000.0
    last_d = trades[0]["entry_ts"].date()
    last_w = trades[0]["entry_ts"].isocalendar()[1]
    last_m = trades[0]["entry_ts"].month
    blocked_until = None

    def close_due(now):
        nonlocal cash, equity, peak_equity
        still = []
        for p in open_pos:
            if p["exit_ts"] <= now:
                holding = (p["exit_ts"] - p["entry_ts"]).total_seconds() / 86400
                f = p["margin"] * p["lev"] * fund_d * holding
                pnl = p["risk"] * p["R"] - f
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

        # Recovery mode: DD bandlarına göre lev cap
        cur_dd = (peak_equity - equity) / peak_equity if peak_equity > 0 else 0
        effective_lev = t["lev"]
        if recovery_mode:
            if cur_dd > 0.30:
                continue  # halt
            elif cur_dd > 0.20:
                effective_lev = min(effective_lev, 2.0)
            elif cur_dd > 0.15:
                effective_lev = min(effective_lev, 3.0)

        # Volatility scaling
        if vol_scaling:
            if t["atr_pct"] > 0.07:  # >%7 ATR = high vol
                effective_lev = min(effective_lev, 1.0)
            elif t["atr_pct"] > 0.05:  # %5-7 ATR = orta-yüksek
                effective_lev = min(effective_lev, 2.0)

        cd = t["entry_ts"].date()
        cw = t["entry_ts"].isocalendar()[1]
        cm = t["entry_ts"].month
        if cd != last_d: daily_anchor = equity; last_d = cd
        if cw != last_w: weekly_anchor = equity; last_w = cw
        if cm != last_m: monthly_anchor = equity; last_m = cm
        if blocked_until and t["entry_ts"] < blocked_until: continue
        if (daily_anchor - equity) / max(daily_anchor, 1) >= daily_dd:
            blocked_until = t["entry_ts"] + timedelta(days=1); continue
        if (weekly_anchor - equity) / max(weekly_anchor, 1) >= weekly_dd:
            blocked_until = t["entry_ts"] + timedelta(days=7); continue
        if (monthly_anchor - equity) / max(monthly_anchor, 1) >= monthly_dd:
            blocked_until = t["entry_ts"] + timedelta(days=30); continue
        if len(open_pos) >= max_concurrent: continue
        sl_pct = abs(t["entry_price"] - t["initial_sl"]) / t["entry_price"]
        if sl_pct <= 0: continue
        risk_d = equity * risk_pct
        notional = risk_d / sl_pct
        margin = notional / effective_lev
        if margin > cash: continue
        cash -= margin
        open_pos.append({
            "entry_ts": t["entry_ts"], "exit_ts": t["exit_ts"],
            "margin": margin, "risk": risk_d, "R": t["R"], "lev": effective_lev,
        })

    for p in open_pos:
        holding = (p["exit_ts"] - p["entry_ts"]).total_seconds() / 86400
        f = p["margin"] * p["lev"] * fund_d * holding
        cash += p["margin"] + p["risk"] * p["R"] - f
        equity = cash
        eq_curve.append(equity)

    peak = eq_curve[0]
    max_dd = 0
    for v in eq_curve:
        if v > peak: peak = v
        dd = (v - peak) / peak
        if dd < max_dd: max_dd = dd
    return {"final": equity, "max_dd": max_dd}


def yearly_breakdown(trades, **kwargs):
    """Her yıl ayrı $10K başlat, getirileri topla. Yıllar arası σ hesapla."""
    start = trades[0]["entry_ts"]
    rets = []
    dds = []
    for yr in range(3):
        ws = start + timedelta(days=365 * yr)
        we = start + timedelta(days=365 * (yr + 1))
        wt = [t for t in trades if ws <= t["entry_ts"] < we]
        r = replay(wt, **kwargs)
        if r is None: continue
        rets.append(r["final"] / 10_000 - 1)
        dds.append(r["max_dd"])
    if not rets:
        return None
    eq_compound = 10_000.0
    for ret in rets:
        eq_compound *= (1 + ret)
    annual = ((eq_compound / 10_000) ** (1 / len(rets)) - 1) * 100
    sigma = (sum((x - sum(rets)/len(rets))**2 for x in rets) / len(rets)) ** 0.5 * 100
    worst_dd = min(dds) * 100
    return {
        "annual": annual,
        "compound_3y": (eq_compound / 10_000 - 1) * 100,
        "sigma": sigma,
        "worst_dd": worst_dd,
        "yearly_rets": [r * 100 for r in rets],
        "yearly_dds": [d * 100 for d in dds],
        "final": eq_compound,
    }


def main():
    print("=== DD-AZALTMA OPTİMİZASYON SWEEP ===\n")
    print("Trade'leri topluyor...")
    trades = _gather_engulfing()
    print(f"Toplam {len(trades)} trade\n")

    if not trades:
        return

    configs = [
        ("1. BASELINE Production A (R%2, lev1-5x, 5/10/15)", {}),
        ("2. Risk %1.5 (lev1-5x, 5/10/15)", {"risk_pct": 0.015}),
        ("3. Risk %1 (lev1-5x, 5/10/15) — defansif", {"risk_pct": 0.01}),
        ("4. Max concurrent 3 (R%2)", {"max_concurrent": 3}),
        ("5. Sıkı breaker (R%2, 3/7/12)", {"daily_dd": 0.03, "weekly_dd": 0.07, "monthly_dd": 0.12}),
        ("6. Recovery mode (R%2, DD bands cap)", {"recovery_mode": True}),
        ("7. Vol-scaling (R%2, high ATR cap lev1)", {"vol_scaling": True}),
        ("8. Combined defensive (R%1.5+conc3+breaker3/7/12)", {"risk_pct": 0.015, "max_concurrent": 3, "daily_dd": 0.03, "weekly_dd": 0.07, "monthly_dd": 0.12}),
        ("9. Combined moderate (R%1.5+recovery)", {"risk_pct": 0.015, "recovery_mode": True}),
        ("10. Combined aggressive (R%1.5+vol-scale+recovery)", {"risk_pct": 0.015, "recovery_mode": True, "vol_scaling": True}),
    ]

    print(f"{'Konfig':<60} {'Yıl1':>7} {'Yıl2':>7} {'Yıl3':>7} {'σ':>6} {'Yıllık':>8} {'Compound':>10} {'maxDD':>7}")
    print("-" * 130)

    results = []
    for label, kwargs in configs:
        r = yearly_breakdown(trades, **kwargs)
        if r is None: continue
        cells = " ".join(f"{rr:>+6.1f}%" for rr in r["yearly_rets"])
        # 3 yıl olmasa bile pad
        while len(r["yearly_rets"]) < 3:
            cells += "      -"
        print(f"{label:<60} {cells} {r['sigma']:>5.1f}% {r['annual']:>+7.2f}% +{r['compound_3y']:>6.0f}% {r['worst_dd']:>+5.1f}%")
        results.append((label, r))

    print()
    print("=" * 130)
    print("HEDEF: yıllık > %50 + maxDD < %30 + σ < %30")
    print("=" * 130)
    candidates = [r for r in results if r[1]["annual"] > 50 and abs(r[1]["worst_dd"]) < 30]
    if candidates:
        print("\nHEDEFE ULAŞAN KONFIGLER:")
        for label, r in candidates:
            print(f"  ✓ {label}")
            print(f"    Yıllık {r['annual']:.1f}%, DD {r['worst_dd']:.1f}%, σ {r['sigma']:.1f}%, $10K → ${r['final']:,.0f}")
    else:
        print("\nHEDEFE ULAŞAN KONFIG YOK. En yakınlar:")
        for label, r in sorted(results, key=lambda x: x[1]["annual"] - 2*abs(x[1]["worst_dd"]), reverse=True)[:3]:
            print(f"  ~ {label}")
            print(f"    Yıllık {r['annual']:.1f}%, DD {r['worst_dd']:.1f}%, σ {r['sigma']:.1f}%, $10K → ${r['final']:,.0f}")


if __name__ == "__main__":
    main()
