"""Production A konfig (R%2 lev 1-5x dinamik, scaling OFF) — yıl bazında breakdown.

Multi-strategy script'inde +%81.10 yıllık veren konfig'in 1-yıllık pencereler halinde
testi: Yıl 1 / Yıl 2 / Yıl 3 ne kadar getiri verdi?
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


def _gather_engulfing_with_features():
    """Tam Production A trade dataset — confidence + lev tier dahil."""
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
            rs60 = float(df_feats["rolling_sharpe_60"].iloc[idx])
            body = float(df_feats["body_ratio"].iloc[idx])
            if np.isnan(rs60): rs60 = 0
            if np.isnan(body): body = 0
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
                "conf": conf, "lev": lev,
            })
    out.sort(key=lambda x: x["entry_ts"])
    return out


def replay_production_a(trades, daily_dd=0.05, weekly_dd=0.10, monthly_dd=0.15,
                       fund_annual=0.10, max_concurrent=5, risk_pct=0.02):
    """Production A: $10K, R%2, lev 1-5x dinamik, breaker'lar aktif."""
    if not trades:
        return None
    trades = sorted(trades, key=lambda t: t["entry_ts"])
    equity = 10_000.0
    cash = 10_000.0
    open_pos = []
    Rs = []
    eq_curve = [10_000.0]
    lev_dist = {1.0: 0, 2.0: 0, 3.0: 0, 4.0: 0, 5.0: 0}
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
        risk_d = equity * risk_pct
        notional = risk_d / sl_pct
        margin = notional / t["lev"]
        if margin > cash: continue
        cash -= margin
        open_pos.append({
            "entry_ts": t["entry_ts"], "exit_ts": t["exit_ts"],
            "margin": margin, "risk": risk_d, "R": t["R"], "lev": t["lev"],
        })
        lev_dist[t["lev"]] += 1

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
    avg_R = sum(Rs) / len(Rs) if Rs else 0
    return {
        "final": equity, "trades": len(Rs),
        "win_rate": win, "avg_R": avg_R,
        "max_dd": max_dd, "lev_dist": lev_dist,
    }


def main():
    print("=== Production A (R%2 lev 1-5x dinamik) — Yıl Bazında Breakdown ===\n")
    print("Trade'leri topluyor (engulfing + features)...")
    all_trades = _gather_engulfing_with_features()
    print(f"Toplam {len(all_trades)} trade\n")

    if not all_trades:
        return

    # Conf dağılımı
    confs = [t["conf"] for t in all_trades]
    print("--- Confidence dağılımı ---")
    print(f"  min: {min(confs):.3f}, max: {max(confs):.3f}, mean: {sum(confs)/len(confs):.3f}")

    # 3 yıllık pencere — calendar year değil, data start'tan + 365 gün
    start = all_trades[0]["entry_ts"]
    end = all_trades[-1]["exit_ts"]
    print(f"Veri penceresi: {start.date()} → {end.date()}\n")

    # Yıl pencere replay
    print(f"{'Pencere':<35} {'trade':>7} {'final$':>10} {'getiri':>9} {'win%':>6} {'avgR':>7} {'maxDD':>7}")
    print(f"{'(her pencere $10K start)':<35}")
    print("-" * 95)

    yearly_results = []
    for yr in range(3):
        ws = start + timedelta(days=365 * yr)
        we = start + timedelta(days=365 * (yr + 1))
        wt = [t for t in all_trades if ws <= t["entry_ts"] < we]
        r = replay_production_a(wt)
        if r is None:
            continue
        ret = r["final"] / 10_000 - 1
        yearly_results.append((yr+1, ws, we, r, ret))
        label = f"Yıl {yr+1} ({ws.date()} → {we.date()})"
        print(f"{label:<35} {r['trades']:>7} {r['final']:>10,.0f} {ret*100:>+8.2f}% {r['win_rate']*100:>5.1f}% {r['avg_R']:>+7.2f} {r['max_dd']*100:>+6.1f}%")

    # Compound chain
    print("\n--- COMPOUNDING ZINCIRI (her yıl önceki yılın final'ından başlasaydı) ---")
    eq = 10_000.0
    print(f"  Başlangıç: ${eq:,.0f}")
    for yr, ws, we, r, ret in yearly_results:
        eq *= (1 + ret)
        print(f"  Yıl {yr}: {ret*100:+.2f}% → ${eq:,.0f}")
    annual = ((eq / 10_000) ** (1 / len(yearly_results)) - 1) * 100
    print(f"\n  3y compound final  : ${eq:,.0f} (+{(eq/10_000-1)*100:.2f}%)")
    print(f"  Yıllık ortalama    : {annual:+.2f}%")

    # En iyi / en kötü yıl
    rets = [x[4] for x in yearly_results]
    best = max(rets)
    worst = min(rets)
    print(f"\n  En iyi yıl  : {best*100:+.2f}%")
    print(f"  En kötü yıl : {worst*100:+.2f}%")
    print(f"  Volatilite σ: {(sum((x-sum(rets)/len(rets))**2 for x in rets)/len(rets))**0.5*100:.2f}%")

    # 6-ay breakdown — daha granular görüş
    print("\n--- 6-AYLIK PENCERELER ---")
    print(f"{'Pencere':<35} {'trade':>7} {'final$':>10} {'getiri':>9} {'win%':>6}")
    print("-" * 80)
    for half in range(6):
        ws = start + timedelta(days=183 * half)
        we = start + timedelta(days=183 * (half + 1))
        wt = [t for t in all_trades if ws <= t["entry_ts"] < we]
        r = replay_production_a(wt)
        if r is None: continue
        ret = r["final"] / 10_000 - 1
        label = f"6ay {half+1} ({ws.date()} → {we.date()})"
        print(f"{label:<35} {r['trades']:>7} {r['final']:>10,.0f} {ret*100:>+8.2f}% {r['win_rate']*100:>5.1f}%")

    # $200 base ile aynı
    print("\n--- $200 GERÇEKÇİ BASE (compound) ---")
    eq200 = 200.0
    for yr, ws, we, r, ret in yearly_results:
        eq200 *= (1 + ret)
        print(f"  Yıl {yr}: $200 başlangıç + compound → ${eq200:,.2f}")


if __name__ == "__main__":
    main()
