"""HEDEF %50 - iterasyon 2.

Bulgular:
  Top 5 (1d) + dyn 1-4 + max_concurrent 8 = yillik %27.13 ⭐
  4h ekleme zarar verdi (overcrowd)

Yeni denemeler:
  1. confidence MIN filter (dusuk conf'leri ele)
  2. R cutoff (sadece avg R > 0.3 stratejiler)
  3. Daha cok strateji (10+)
  4. WR-weighted strategy mix (yuksek WR'ye daha cok agirlik)
"""
from __future__ import annotations

import io
import sys
from datetime import timedelta
from pathlib import Path

import numpy as np
import pandas as pd

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))
sys.path.insert(0, str(ROOT))


SYMBOLS = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT",
           "ADA/USDT", "AVAX/USDT", "LINK/USDT", "DOT/USDT"]


# Tum 1d strateji adaylari (avg_r > 0)
STRATEGIES_1D = [
    ("engulfing_continuation", "EngulfingContinuationStrategy"),
    ("pin_bar_round_numbers", "PinBarRoundNumbersStrategy"),
    ("obv_engulfing_confluence", "OBVEngulfingConfluenceStrategy"),
    ("morning_evening_star", "MorningEveningStarStrategy"),
    ("equal_highs_sweep", "EqualHighsSweepStrategy"),
    ("three_black_crows", "ThreeBlackCrowsStrategy"),  # +0.78 avg R
    ("wyckoff_phase_d", "WyckoffPhaseDStrategy"),  # %62 WR
]


def _gather_for(module_name, class_name, tf="1d"):
    from price_action.backtest.engine import BacktestEngine
    from scripts.run_real_backtest import _load_symbol_ohlcv
    try:
        mod = __import__(f"price_action.strategies.{module_name}", fromlist=[class_name, "_default_manifest"])
        cls = getattr(mod, class_name)
        manifest_fn = getattr(mod, "_default_manifest", None)
        if not manifest_fn: return []
        s = cls(manifest_fn())
    except Exception:
        return []
    out = []
    for sym in SYMBOLS:
        try:
            df = _load_symbol_ohlcv(sym, tf=tf)
            if df is None or df.empty: continue
            df = df.sort_values("ts").reset_index(drop=True)
            df["symbol"] = sym; df["venue"] = "binance"; df["timeframe"] = tf
            def prov(*a, **k): return df.copy()
            e = BacktestEngine(risk_officer=None, store_load=None)
            r = e.run(s, [sym], start=df["ts"].iloc[0].to_pydatetime(),
                     end=df["ts"].iloc[-1].to_pydatetime(), timeframe=tf,
                     initial_capital=10_000.0, fees={"taker":0.00075,"maker":-0.00010},
                     slippage_bps=5.0, ohlcv_provider=prov)
            for _, t in r.trades.iterrows():
                conf = max(0.0, min(1.0, (float(t["confluence_score"]) - 1.5) / 1.5))
                ts_e = pd.Timestamp(t["entry_ts"])
                if ts_e.tzinfo is None: ts_e = ts_e.tz_localize("UTC")
                ts_x = pd.Timestamp(t["exit_ts"])
                if ts_x.tzinfo is None: ts_x = ts_x.tz_localize("UTC")
                out.append({
                    "entry_ts": ts_e, "exit_ts": ts_x,
                    "entry_price": float(t["entry_price"]), "initial_sl": float(t["initial_sl"]),
                    "R": float(t["realized_r_multiple"]), "symbol": sym, "side": str(t["side"]),
                    "conf": conf, "strategy": module_name, "tf": tf,
                })
        except Exception:
            continue
    return out


def conf_to_risk_dyn(conf):
    if conf < 0.32: return 0.010
    if conf < 0.42: return 0.015
    if conf < 0.52: return 0.020
    if conf < 0.58: return 0.030
    return 0.040


def replay_portfolio(trades, risk_fn, max_concurrent=8, cooldown_days=3, conf_min=0.0):
    if not trades: return None
    trades = [t for t in trades if t["conf"] >= conf_min]
    if not trades: return None
    trades = sorted(trades, key=lambda t: t["entry_ts"])
    equity = 10_000.0; cash = 10_000.0
    open_pos = []; eq_curve = [10_000.0]; Rs = []
    daily_anchor = weekly_anchor = monthly_anchor = 10_000.0
    last_d = trades[0]["entry_ts"].date()
    last_w = trades[0]["entry_ts"].isocalendar()[1]
    last_m = trades[0]["entry_ts"].month
    blocked_until = None
    last_entry: dict[tuple, pd.Timestamp] = {}

    def close_due(now):
        nonlocal cash, equity
        still = []
        for p in open_pos:
            if p["exit_ts"] <= now:
                pnl = p["risk"] * p["R"]
                cash += p["margin"] + pnl
                equity = cash + sum(q["margin"] for q in still)
                Rs.append(p["R"])
                eq_curve.append(equity)
            else: still.append(p)
        open_pos[:] = still

    for t in trades:
        close_due(t["entry_ts"])
        key = (t["symbol"], t["side"])
        prev = last_entry.get(key)
        if prev is not None and (t["entry_ts"] - prev).days < cooldown_days: continue
        cd = t["entry_ts"].date(); cw = t["entry_ts"].isocalendar()[1]; cm = t["entry_ts"].month
        if cd != last_d: daily_anchor = equity; last_d = cd
        if cw != last_w: weekly_anchor = equity; last_w = cw
        if cm != last_m: monthly_anchor = equity; last_m = cm
        if blocked_until and t["entry_ts"] < blocked_until: continue
        if (daily_anchor - equity)/max(daily_anchor,1) >= 0.05:
            blocked_until = t["entry_ts"] + timedelta(days=1); continue
        if (weekly_anchor - equity)/max(weekly_anchor,1) >= 0.10:
            blocked_until = t["entry_ts"] + timedelta(days=7); continue
        if (monthly_anchor - equity)/max(monthly_anchor,1) >= 0.15:
            blocked_until = t["entry_ts"] + timedelta(days=30); continue
        if len(open_pos) >= max_concurrent: continue
        sl_pct = abs(t["entry_price"] - t["initial_sl"])/t["entry_price"]
        if sl_pct <= 0: continue
        risk_pct = risk_fn(t["conf"])
        risk_d = equity * risk_pct
        notional = risk_d / sl_pct
        margin = notional / 3.0
        if margin > cash: continue
        cash -= margin
        last_entry[key] = t["entry_ts"]
        open_pos.append({"exit_ts": t["exit_ts"], "margin": margin, "risk": risk_d, "R": t["R"]})

    for p in open_pos:
        cash += p["margin"] + p["risk"] * p["R"]
        equity = cash; Rs.append(p["R"])
        eq_curve.append(equity)

    peak = eq_curve[0]; max_dd = 0
    for v in eq_curve:
        if v > peak: peak = v
        dd = (v - peak)/peak
        if dd < max_dd: max_dd = dd

    win = sum(1 for x in Rs if x > 0)/len(Rs) if Rs else 0
    avg_r = np.mean(Rs) if Rs else 0
    return {"final": equity, "max_dd": max_dd, "trades": len(Rs), "wr": win, "avg_r": avg_r}


def main():
    print("=" * 80)
    print("HUNT %50 — iterasyon 2 (conf filter + 7 strateji)")
    print("=" * 80)

    all_trades = []
    for module_name, class_name in STRATEGIES_1D:
        print(f"  {module_name}...", end=" ")
        trs = _gather_for(module_name, class_name, tf="1d")
        print(f"{len(trs)} sinyal")
        all_trades.extend(trs)

    all_trades.sort(key=lambda x: x["entry_ts"])
    print(f"\nTOPLAM {len(all_trades)} sinyal\n")

    print("=" * 100)
    print(f"{'Senaryo':<48} {'sinyal':>7} {'yIllIk':>8} {'maxDD':>7} {'WR':>5} {'final$':>10}")
    print("-" * 100)

    scenarios = [
        ("Top 7 dyn 1-4 max8 cooldown3 conf>=0",     all_trades, conf_to_risk_dyn, 8, 3, 0.0),
        ("Top 7 dyn 1-4 max8 cooldown3 conf>=0.30",  all_trades, conf_to_risk_dyn, 8, 3, 0.30),
        ("Top 7 dyn 1-4 max8 cooldown3 conf>=0.40",  all_trades, conf_to_risk_dyn, 8, 3, 0.40),
        ("Top 7 dyn 1-4 max8 cooldown3 conf>=0.50",  all_trades, conf_to_risk_dyn, 8, 3, 0.50),
        ("Top 7 dyn 2-5% max8 conf>=0.40",           all_trades, lambda c: 0.020 if c < 0.42 else (0.030 if c < 0.52 else (0.040 if c < 0.58 else 0.050)), 8, 3, 0.40),
        ("Top 7 dyn 2-6% max8 conf>=0.40",           all_trades, lambda c: 0.020 if c < 0.42 else (0.035 if c < 0.52 else (0.050 if c < 0.58 else 0.060)), 8, 3, 0.40),
        ("Top 7 dyn 1-4 max12 cooldown1 conf>=0.30", all_trades, conf_to_risk_dyn, 12, 1, 0.30),
        ("Top 7 dyn 1-4 max15 cooldown1 conf>=0.30", all_trades, conf_to_risk_dyn, 15, 1, 0.30),
    ]

    best = None
    for name, ts, fn, mc, cd, cm in scenarios:
        if not ts: continue
        r = replay_portfolio(ts, risk_fn=fn, max_concurrent=mc, cooldown_days=cd, conf_min=cm)
        if r is None: continue
        ret = (r["final"]/10000-1)*100
        ann = ((r["final"]/10000)**(1/5)-1)*100
        print(f"{name:<48} {r['trades']:>7} {ann:>+7.2f}% {r['max_dd']*100:>+6.1f}% {r['wr']*100:>4.0f}% {r['final']:>10,.0f}")
        if best is None or ann > best[1]:
            best = (name, ann, r)

    print()
    if best:
        print(f"EN IYI: {best[0]}")
        print(f"  Yillik: {best[1]:+.2f}%")
        print(f"  $10K -> 5y -> ${best[2]['final']:,.0f}")
        if best[1] >= 50:
            print(f"  HEDEF (%50) BASARILDI! ⭐")
        elif best[1] >= 30:
            print(f"  Yari yol ({best[1]:.0f}%)")


if __name__ == "__main__":
    main()
