"""2026 Ocak'tan bugüne $10K bot replay — detaylı trade listesi.

Production konfig: engulfing_continuation, 8 sembol, R%2, lev 1-5x dynamic
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))
sys.path.insert(0, str(ROOT))


SYMBOLS = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT",
           "ADA/USDT", "AVAX/USDT", "LINK/USDT", "DOT/USDT"]


def _gather():
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
                "entry_ts": pd.Timestamp(t["entry_ts"]),
                "exit_ts": pd.Timestamp(t["exit_ts"]),
                "entry_price": float(t["entry_price"]),
                "exit_price": float(t["exit_price"]) if not pd.isna(t["exit_price"]) else None,
                "initial_sl": float(t["initial_sl"]),
                "initial_tp": float(t["initial_tp"]) if not pd.isna(t["initial_tp"]) else None,
                "R": float(t["realized_r_multiple"]),
                "symbol": sym,
                "side": str(t["side"]),
                "pattern": str(t["pattern_id"]),
                "conf": conf, "lev": lev,
            })
    out.sort(key=lambda x: x["entry_ts"])
    return out


def main():
    print("=" * 95)
    print("BOT REPLAY — 2026 Ocak başından bugüne ($10K start)")
    print("Production konfig: engulfing_continuation, 8 sembol, R%2, lev 1-5x dynamic")
    print("=" * 95)
    print()
    print("Trade'leri topluyor...")
    all_trades = _gather()

    # 2026-01-01'den bugüne filtrele
    start_filter = pd.Timestamp("2026-01-01", tz="UTC")
    trades_2026 = [t for t in all_trades if t["entry_ts"] >= start_filter]
    print(f"2026 Ocak başından bugüne: {len(trades_2026)} sinyal\n")

    if not trades_2026:
        print("2026'da sinyal yok!")
        return

    # Tek hesap simülasyon
    initial = 10_000.0
    equity = initial
    cash = initial
    open_pos = []
    closed_trades = []
    Rs = []
    fund_d = 0.10 / 365  # %10 yıllık funding lev başına
    daily_anchor = weekly_anchor = monthly_anchor = initial
    last_d = trades_2026[0]["entry_ts"].date()
    last_w = trades_2026[0]["entry_ts"].isocalendar()[1]
    last_m = trades_2026[0]["entry_ts"].month
    blocked_until = None

    def close_due(now):
        nonlocal cash, equity
        still = []
        for p in open_pos:
            if p["exit_ts"] <= now:
                holding = (p["exit_ts"] - p["entry_ts"]).total_seconds() / 86400
                fund = p["margin"] * p["lev"] * fund_d * holding
                pnl = p["risk"] * p["R"] - fund
                cash += p["margin"] + pnl
                equity = cash + sum(q["margin"] for q in still)
                Rs.append(p["R"])
                p["pnl"] = pnl
                p["equity_after"] = equity
                p["holding_days"] = holding
                closed_trades.append(p)
            else:
                still.append(p)
        open_pos[:] = still

    skip_concurrent = 0
    skip_cash = 0
    skip_breaker = 0

    for t in trades_2026:
        close_due(t["entry_ts"])
        cd = t["entry_ts"].date()
        cw = t["entry_ts"].isocalendar()[1]
        cm = t["entry_ts"].month
        if cd != last_d: daily_anchor = equity; last_d = cd
        if cw != last_w: weekly_anchor = equity; last_w = cw
        if cm != last_m: monthly_anchor = equity; last_m = cm

        if blocked_until and t["entry_ts"] < blocked_until:
            skip_breaker += 1; continue
        if (daily_anchor - equity) / max(daily_anchor, 1) >= 0.05:
            blocked_until = t["entry_ts"] + timedelta(days=1); skip_breaker += 1; continue
        if (weekly_anchor - equity) / max(weekly_anchor, 1) >= 0.10:
            blocked_until = t["entry_ts"] + timedelta(days=7); skip_breaker += 1; continue
        if (monthly_anchor - equity) / max(monthly_anchor, 1) >= 0.15:
            blocked_until = t["entry_ts"] + timedelta(days=30); skip_breaker += 1; continue
        if len(open_pos) >= 5:
            skip_concurrent += 1; continue

        sl_pct = abs(t["entry_price"] - t["initial_sl"]) / t["entry_price"]
        if sl_pct <= 0: continue
        risk_d = equity * 0.02
        notional = risk_d / sl_pct
        margin = notional / t["lev"]
        if margin > cash:
            skip_cash += 1; continue
        cash -= margin
        new_pos = {
            **t,
            "margin": margin,
            "risk": risk_d,
            "notional": notional,
            "equity_at_entry": equity,
        }
        open_pos.append(new_pos)

    # Force close remaining
    for p in open_pos:
        holding = (p["exit_ts"] - p["entry_ts"]).total_seconds() / 86400
        fund = p["margin"] * p["lev"] * fund_d * holding
        pnl = p["risk"] * p["R"] - fund
        cash += p["margin"] + pnl
        equity = cash
        Rs.append(p["R"])
        p["pnl"] = pnl
        p["equity_after"] = equity
        p["holding_days"] = holding
        closed_trades.append(p)

    # ---- LIST TRADES ----
    print(f"{'#':>3} {'Tarih':<11} {'Sembol':<10} {'Yön':<5} {'Lev':>3} {'Conf':>5} {'Entry':>10} {'Exit':>10} {'R':>6} {'Notional':>10} {'P&L':>10} {'Equity':>10}")
    print("-" * 100)
    for i, p in enumerate(closed_trades, 1):
        date_str = p["entry_ts"].strftime("%Y-%m-%d")
        side = "LONG" if p["side"] == "long" else "SHORT"
        ent = f"${p['entry_price']:>9,.2f}"
        ext = f"${p['exit_price']:>9,.2f}" if p.get('exit_price') else "  -open- "
        pnl_str = f"+${p['pnl']:>7.2f}" if p['pnl'] > 0 else f"-${abs(p['pnl']):>7.2f}"
        print(f"{i:>3} {date_str:<11} {p['symbol']:<10} {side:<5} {int(p['lev']):>3}x {p['conf']:>5.2f} {ent:>10} {ext:>10} {p['R']:>+6.2f} ${p['notional']:>8,.0f} {pnl_str:>10} ${p['equity_after']:>9,.0f}")

    # ---- SUMMARY ----
    print()
    print("=" * 95)
    print("ÖZET")
    print("=" * 95)
    n_total = len(closed_trades)
    win = sum(1 for p in closed_trades if p['pnl'] > 0)
    loss = n_total - win
    total_pnl = equity - initial
    print(f"Başlangıç sermaye   : ${initial:,.2f}")
    print(f"Şu anki sermaye      : ${equity:,.2f}")
    print(f"Net P&L              : {'+' if total_pnl >= 0 else ''}${total_pnl:,.2f} ({(total_pnl/initial)*100:+.2f}%)")
    print(f"Yıllıklandırılmış    : {((equity/initial)**(365/((trades_2026[-1]['entry_ts']-start_filter).days or 1))-1)*100:+.1f}% (yıllık equiv)")
    print()
    print(f"Toplam sinyal        : {len(trades_2026)}")
    print(f"Açılan trade         : {n_total}")
    print(f"  ↑ Skip max-concurrent: {skip_concurrent}")
    print(f"  ↑ Skip cash yetersiz : {skip_cash}")
    print(f"  ↑ Skip DD breaker    : {skip_breaker}")
    print(f"Kazanç               : {win} ({100*win/n_total:.0f}%)")
    print(f"Zarar                : {loss} ({100*loss/n_total:.0f}%)")
    print(f"Avg R-multiple       : {sum(p['R'] for p in closed_trades)/n_total:+.2f}")
    print(f"Toplam holding gün   : {sum(p.get('holding_days', 0) for p in closed_trades):.0f}")

    # ---- PER-COIN ----
    print()
    print("--- PER-COIN BREAKDOWN ---")
    print(f"{'Sembol':<10} {'Trade':>5} {'Long':>5} {'Short':>5} {'Win':>4} {'Loss':>5} {'WR%':>5} {'Toplam P&L':>12} {'Avg P&L':>9}")
    print("-" * 75)
    by_sym = {}
    for p in closed_trades:
        s = p['symbol']
        if s not in by_sym:
            by_sym[s] = {"n":0, "long":0, "short":0, "win":0, "loss":0, "pnl":0}
        by_sym[s]["n"] += 1
        if p['side'] == 'long': by_sym[s]["long"] += 1
        else: by_sym[s]["short"] += 1
        if p['pnl'] > 0: by_sym[s]["win"] += 1
        else: by_sym[s]["loss"] += 1
        by_sym[s]["pnl"] += p['pnl']

    for sym in sorted(by_sym, key=lambda x: -by_sym[x]["pnl"]):
        d = by_sym[sym]
        wr = 100 * d["win"] / d["n"] if d["n"] else 0
        avg = d["pnl"] / d["n"]
        print(f"{sym:<10} {d['n']:>5} {d['long']:>5} {d['short']:>5} {d['win']:>4} {d['loss']:>5} {wr:>4.0f}% {'+' if d['pnl']>=0 else ''}${d['pnl']:>9,.2f} {'+' if avg>=0 else ''}${avg:>7,.2f}")

    # Sembollerden kazanmayan/kaybedmeyen
    no_trade = set(SYMBOLS) - set(by_sym.keys())
    if no_trade:
        print(f"\nSinyal hiç atmayan sembol: {', '.join(sorted(no_trade))}")


if __name__ == "__main__":
    main()
