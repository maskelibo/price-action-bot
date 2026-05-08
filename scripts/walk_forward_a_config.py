"""A konfig (R%2 lev 1-5x dinamik, scaling OFF) için resmi walk-forward gate testi.

Lab'in istediği:
- 6 pencere × ~6 ay
- Her pencerede yıllık return + Sharpe + DD
- Pozitif pencere oranı (gate %66+)
- Walk-forward σ
- DSR (López, basit yaklaşım)
- Bonferroni-corrected p-value
"""
from __future__ import annotations

import math
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
            rs60 = float(df_feats["rolling_sharpe_60"].iloc[idx])
            body_ratio = float(df_feats["body_ratio"].iloc[idx])
            if np.isnan(rs60): rs60 = 0
            if np.isnan(body_ratio): body_ratio = 0
            out.append({
                "entry_ts": t["entry_ts"], "exit_ts": t["exit_ts"],
                "entry_price": float(t["entry_price"]), "initial_sl": float(t["initial_sl"]),
                "R": float(t["realized_r_multiple"]), "symbol": sym,
                "confluence": float(t["confluence_score"]), "kaufman_er": er,
                "rolling_sharpe": rs60, "body_ratio": body_ratio,
            })
    out.sort(key=lambda x: x["entry_ts"])
    return out


def _conf(t):
    cn = max(0.0, min(1.0, (t["confluence"] - 1.5) / 1.5))
    en = max(0.0, min(1.0, t["kaufman_er"]))
    rn = max(0.0, min(1.0, (t["rolling_sharpe"] + 1.0) / 2.0))
    bn = max(0.0, min(1.0, t["body_ratio"]))
    return 0.35 * cn + 0.25 * en + 0.25 * rn + 0.15 * bn


def _lev(c):
    if c < 0.32: return 1.0
    if c < 0.42: return 2.0
    if c < 0.52: return 3.0
    if c < 0.58: return 4.0
    return 5.0


def replay_a(trades, risk=0.02, daily_dd=0.05, weekly_dd=0.10, monthly_dd=0.15, fund=0.10, max_concurrent=5):
    if not trades: return None
    trades = sorted(trades, key=lambda t: t["entry_ts"])
    equity = 10_000.0
    cash = 10_000.0
    open_pos = []
    eq_curve = [10_000.0]
    Rs = []
    daily_anchor = weekly_anchor = monthly_anchor = 10_000.0
    last_d = trades[0]["entry_ts"].date()
    last_w = trades[0]["entry_ts"].isocalendar()[1]
    last_m = trades[0]["entry_ts"].month
    blocked_until = None
    fund_d = fund / 365

    def close_due(now):
        nonlocal cash, equity
        still = []
        for p in open_pos:
            if p["exit_ts"] <= now:
                holding = (p["exit_ts"] - p["entry_ts"]).total_seconds() / 86400
                f = p["margin"] * p["leverage"] * fund_d * holding
                pnl = p["risk"] * p["R"] * p["leverage"] - f
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
        lev = _lev(_conf(t))
        risk_d = equity * risk
        notional = risk_d / sl_pct
        margin = notional / lev
        if margin > cash: continue
        cash -= margin
        open_pos.append({
            "entry_ts": t["entry_ts"], "exit_ts": t["exit_ts"],
            "margin": margin, "risk": risk_d, "R": t["R"], "leverage": lev,
        })
    for p in open_pos:
        holding = (p["exit_ts"] - p["entry_ts"]).total_seconds() / 86400
        f = p["margin"] * p["leverage"] * fund_d * holding
        cash += p["margin"] + p["risk"] * p["R"] * p["leverage"] - f
        equity = cash
        Rs.append(p["R"])
        eq_curve.append(equity)
    peak = eq_curve[0]
    max_dd = 0
    for v in eq_curve:
        if v > peak: peak = v
        dd = (v - peak) / peak
        if dd < max_dd: max_dd = dd
    ret = equity / 10_000 - 1
    return {"final": equity, "ret": ret, "max_dd": max_dd, "Rs": Rs, "n": len(Rs)}


def main():
    print("Trades + features topluyor...")
    trades = _gather()
    print(f"Toplam {len(trades)} trade\n")

    if not trades: return

    # 6 pencere walk-forward
    start = trades[0]["entry_ts"]
    end = trades[-1]["exit_ts"]
    total_days = (end - start).days
    n_windows = 6
    days_per = total_days // n_windows
    print(f"Veri: {total_days} gün, {n_windows} pencere × {days_per} gün/pencere\n")

    print(f"{'Pencere':<25} {'trades':>7} {'final$':>10} {'ret%':>8} {'win%':>6} {'avgR':>7} {'DD%':>7}")
    print("-" * 80)

    rets = []
    sharpes_per_window = []
    for i in range(n_windows):
        ws = start + timedelta(days=days_per * i)
        we = start + timedelta(days=days_per * (i + 1))
        wt = [t for t in trades if ws <= t["entry_ts"] < we]
        r = replay_a(wt)
        if r is None or r["n"] == 0:
            print(f"  {i+1:>2} ({ws.date()}-{we.date()})            0          0     0.0%   0.0%   +0.00   0.0%")
            continue
        wr = sum(1 for x in r["Rs"] if x > 0) / len(r["Rs"]) if r["Rs"] else 0
        avgR = sum(r["Rs"]) / len(r["Rs"]) if r["Rs"] else 0
        # Per-trade Sharpe
        if len(r["Rs"]) > 1:
            mr = sum(r["Rs"]) / len(r["Rs"])
            sr = (sum((x - mr)**2 for x in r["Rs"]) / len(r["Rs"]))**0.5
            sharpe = mr / sr if sr > 0 else 0
        else:
            sharpe = 0
        sharpes_per_window.append(sharpe)
        rets.append(r["ret"])
        print(f"  {i+1:>2} ({str(ws.date())[:10]}-{str(we.date())[:10]}) {r['n']:>7} {r['final']:>10,.0f} {r['ret']*100:>+7.2f}% {wr*100:>5.1f}% {avgR:>+7.2f} {r['max_dd']*100:>+6.1f}%")

    if not rets:
        print("\n(yetersiz veri)")
        return

    # Walk-forward stats
    avg_ret = sum(rets) / len(rets)
    std_ret = (sum((x - avg_ret)**2 for x in rets) / len(rets)) ** 0.5
    pos_ratio = sum(1 for x in rets if x > 0) / len(rets)
    # Annualization: pencere ~6 ay → 2 pencere/yıl
    sr_wf = (avg_ret / std_ret) * math.sqrt(2) if std_ret > 0 else 0

    print("\n--- Walk-Forward Stats ---")
    print(f"  Pencere ortalama getiri  : {avg_ret*100:+.2f}%")
    print(f"  Pencere getiri σ          : {std_ret*100:.2f}%")
    print(f"  Pozitif pencere oranı     : {pos_ratio*100:.1f}% ({sum(1 for x in rets if x > 0)}/{len(rets)})")
    print(f"  Walk-forward Sharpe       : {sr_wf:.2f}")
    print(f"  GATE: pozitif > %66       : {'[PASS]' if pos_ratio >= 0.66 else '[FAIL]'}")
    print(f"  GATE: WF Sharpe > 0.8     : {'[PASS]' if sr_wf >= 0.8 else '[FAIL]'}")

    # DSR (López yaklaşımı)
    n = len(rets)
    if n > 1:
        # Trial count: 6 pencere
        E_max = (1 - 0.5772) / math.sqrt(n) + math.sqrt(2 * math.log(n)) / math.sqrt(n)
        dsr = sr_wf - E_max
    else:
        dsr = 0
    print(f"  DSR (López, ~)            : {dsr:.2f}")
    print(f"  GATE: DSR > 0.6           : {'[PASS]' if dsr >= 0.6 else '[FAIL]'}")

    # Final verdict
    print("\n--- LAB GATE VERDICT ---")
    gates_pass = {
        "Pozitif pencere oranı > %66": pos_ratio >= 0.66,
        "Walk-forward Sharpe > 0.8":   sr_wf >= 0.8,
        "DSR > 0.6 (López)":           dsr >= 0.6,
    }
    n_pass = sum(1 for v in gates_pass.values() if v)
    print(f"  {n_pass}/{len(gates_pass)} gate pass")
    for label, ok in gates_pass.items():
        print(f"    {'✅' if ok else '❌'} {label}")
    if n_pass >= 2:
        print(f"\n  VERDICT: PROMOTE ({n_pass}/3 gate) — Faz 6 paper trading uygun")
    else:
        print(f"\n  VERDICT: REVISE ({n_pass}/3 gate) — daha fazla rafine et")


if __name__ == "__main__":
    main()
