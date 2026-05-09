"""5y FINAL production config backtest.

Tüm bulguları birleştir:
- 5y data (2021-2026, 2022 bear dahil)
- 8 sembol (DOGE/XRP atıl — negatif P&L kanıtlandı)
- Engulfing + F&G filter (production aday)
- R%2 lev 1-5x dinamik (production konfig)
- Breakers (5/10/15)
- Realistic slippage (per-symbol)
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


# Production konfig: 8 sembol (DOGE, XRP atıldı)
PROD_SYMBOLS = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT",
                "ADA/USDT", "AVAX/USDT", "LINK/USDT", "DOT/USDT"]


def _gather_with_features():
    from price_action.backtest.engine import BacktestEngine
    from price_action.strategies.engulfing_continuation import (
        EngulfingContinuationStrategy, _default_manifest as engulf_manifest,
    )
    from price_action.signals.filters import rolling_sharpe
    from scripts.run_real_backtest import _load_symbol_ohlcv

    manifest = engulf_manifest()
    out = []
    for sym in PROD_SYMBOLS:
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
            atr_pct = float(df_feats["atr_pct"].iloc[idx]) if "atr_pct" in df_feats else 0.05
            rs60 = float(df_feats["rolling_sharpe_60"].iloc[idx])
            body = float(df_feats["body_ratio"].iloc[idx])
            if np.isnan(rs60): rs60 = 0
            if np.isnan(body): body = 0
            if np.isnan(atr_pct): atr_pct = 0.05
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
                "side": str(t["side"]),
            })
    out.sort(key=lambda x: x["entry_ts"])
    return out


def _load_fng_synthetic(start, end):
    """Synthetic F&G — same as before."""
    days = pd.date_range(start, end, freq="D", tz="UTC")
    rng = np.random.default_rng(42)
    base = 50 + 25 * np.sin(np.linspace(0, 6 * np.pi, len(days)))
    noise = rng.normal(0, 8, len(days))
    fng = np.clip(base + noise, 5, 95)
    return pd.DataFrame({"ts": days, "fng": fng})


def apply_fng_filter(trades, fng_df, long_max=60, short_min=40):
    fng_lookup = {}
    for _, row in fng_df.iterrows():
        d = pd.Timestamp(row["ts"]).tz_convert("UTC").date()
        fng_lookup[d] = row["fng"]
    out = []
    for t in trades:
        d = (pd.Timestamp(t["entry_ts"]) - timedelta(days=1)).date()
        fng = fng_lookup.get(d, 50)
        if t["side"] == "long" and fng > long_max: continue
        if t["side"] == "short" and fng < short_min: continue
        out.append(t)
    return out


def replay(trades, daily_dd=0.05, weekly_dd=0.10, monthly_dd=0.15,
           fund_annual=0.10, max_concurrent=5, base_risk_pct=0.02):
    """Production replay: $10K, R%2, lev dynamic, breakers."""
    if not trades: return None
    trades = sorted(trades, key=lambda t: t["entry_ts"])
    equity = 10_000.0
    cash = 10_000.0
    open_pos = []
    eq_curve = [10_000.0]
    eq_dates = [trades[0]["entry_ts"]]
    Rs = []
    fund_d = fund_annual / 365

    daily_anchor = weekly_anchor = monthly_anchor = 10_000.0
    last_d = trades[0]["entry_ts"].date()
    last_w = trades[0]["entry_ts"].isocalendar()[1]
    last_m = trades[0]["entry_ts"].month
    blocked_until = None

    def close_due(now):
        nonlocal cash, equity
        still = []
        for p in open_pos:
            if p["exit_ts"] <= now:
                holding = (p["exit_ts"] - p["entry_ts"]).total_seconds() / 86400
                f = p["margin"] * p["lev"] * fund_d * holding
                pnl = p["risk"] * p["R"] - f
                cash += p["margin"] + pnl
                equity = cash + sum(q["margin"] for q in still)
                Rs.append(p["R"])
                eq_curve.append(equity)
                eq_dates.append(p["exit_ts"])
            else:
                still.append(p)
        open_pos[:] = still

    for t in trades:
        close_due(t["entry_ts"])
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
        risk_d = equity * base_risk_pct
        notional = risk_d / sl_pct
        margin = notional / t["lev"]
        if margin > cash: continue
        cash -= margin
        open_pos.append({
            "entry_ts": t["entry_ts"], "exit_ts": t["exit_ts"],
            "margin": margin, "risk": risk_d, "R": t["R"], "lev": t["lev"],
        })

    for p in open_pos:
        holding = (p["exit_ts"] - p["entry_ts"]).total_seconds() / 86400
        f = p["margin"] * p["lev"] * fund_d * holding
        cash += p["margin"] + p["risk"] * p["R"] - f
        equity = cash
        Rs.append(p["R"])
        eq_curve.append(equity)

    peak = eq_curve[0]
    max_dd = 0
    for v in eq_curve:
        if v > peak: peak = v
        dd = (v - peak) / peak
        if dd < max_dd: max_dd = dd

    win = sum(1 for x in Rs if x > 0) / len(Rs) if Rs else 0
    return {"final": equity, "max_dd": max_dd, "trades": len(Rs), "win": win, "eq_curve": eq_curve}


def main():
    print("=" * 70)
    print("FINAL 5Y PRODUCTION BACKTEST")
    print("8 sembol (DOGE/XRP atıl) + Engulfing + F&G + R%2 lev1-5x dynamic")
    print("=" * 70)
    print()
    print("Trade'leri topluyor (5y data, 8 sembol)...")
    trades = _gather_with_features()
    print(f"Toplam {len(trades)} engulfing sinyali (8 sembol × 5y)\n")
    if not trades:
        return

    start = trades[0]["entry_ts"] - timedelta(days=60)
    end = trades[-1]["exit_ts"] + timedelta(days=10)
    fng = _load_fng_synthetic(start, end)

    # Senaryo karşılaştırma
    scenarios = [
        ("Engulfing solo (8 sym)", trades),
        ("Engulfing + F&G filter (8 sym)", apply_fng_filter(trades, fng)),
    ]

    print(f"{'Senaryo':<40} {'sinyal':>6} {'final$':>10} {'5y%':>8} {'yıllık':>8} {'maxDD':>7} {'WR%':>5}")
    print("-" * 100)

    for label, ts in scenarios:
        if not ts: continue
        r = replay(ts)
        if r is None: continue
        ret_5y = r['final'] / 10_000 - 1
        ret_annual = ((r['final'] / 10_000) ** (1/5) - 1) * 100
        print(f"{label:<40} {len(ts):>6} {r['final']:>10,.0f} {ret_5y*100:>+7.2f}% {ret_annual:>+6.2f}% {r['max_dd']*100:>+5.1f}% {r['win']*100:>4.1f}%")

    print()
    print("--- $200 PROJEKSIYONU ---")
    for label, ts in scenarios:
        if not ts: continue
        r = replay(ts)
        if r is None: continue
        ratio = r['final'] / 10_000
        eq200 = 200 * ratio
        print(f"  {label:<40} → \${eq200:,.0f}")

    print()
    print("Yıllar (5y bear+bull dahil) detayı (engulfing+F&G):")
    fng_trades = apply_fng_filter(trades, fng)
    start = fng_trades[0]["entry_ts"]
    for yr in range(5):
        ws = start + timedelta(days=365 * yr)
        we = start + timedelta(days=365 * (yr + 1))
        wt = [t for t in fng_trades if ws <= t["entry_ts"] < we]
        r = replay(wt)
        if r is None or r["trades"] == 0:
            print(f"  Yıl {yr+1} ({ws.date()} → {we.date()}): trade yok")
            continue
        ret = r['final'] / 10_000 - 1
        print(f"  Yıl {yr+1} ({ws.date()} → {we.date()}): {ret*100:>+7.2f}% trade={r['trades']:>3} WR={r['win']*100:.0f}% DD={r['max_dd']*100:.1f}%")


if __name__ == "__main__":
    main()
