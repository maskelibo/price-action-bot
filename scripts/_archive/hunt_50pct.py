"""HEDEF: yillik %50 ROI'ye yaklasmak.

Stratejiler:
  Tier 1 (TOP): engulfing_continuation, pin_bar_round_numbers, obv_engulfing_confluence
  Tier 2 (orta): morning_evening_star, three_methods, equal_highs_sweep
  Tier 3 (4h): engulfing_continuation_4h (eger varsa)

Iyilestirmeler:
  - max_concurrent 5 -> 8 (daha cok paralel)
  - dynamic risk 1-4 (user istedigi)
  - same-symbol cooldown gevsek (3 gun)
  - cross-strategy cooldown 1 gun (ayni sembol farkli strateji)
  - Daha cok strateji (5 yerine 3)
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


# 1d stratejiler (production aday)
STRATEGIES_1D = [
    ("engulfing_continuation", "EngulfingContinuationStrategy"),
    ("pin_bar_round_numbers", "PinBarRoundNumbersStrategy"),
    ("obv_engulfing_confluence", "OBVEngulfingConfluenceStrategy"),
    ("morning_evening_star", "MorningEveningStarStrategy"),  # +%0.8 yillik
    ("equal_highs_sweep", "EqualHighsSweepStrategy"),  # +%2.1
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
    except Exception as e:
        print(f"  ! {module_name}: {e}")
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


def conf_to_risk_dyn(conf: float) -> float:
    """1-4 dynamic risk (user istedigi)."""
    if conf < 0.32: return 0.010
    if conf < 0.42: return 0.015
    if conf < 0.52: return 0.020
    if conf < 0.58: return 0.030
    return 0.040


def replay_portfolio(trades, risk_fn, max_concurrent=8, cooldown_days=3):
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

    last_entry: dict[tuple, pd.Timestamp] = {}
    skipped_cooldown = skipped_concurrent = skipped_breaker = 0

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
            else:
                still.append(p)
        open_pos[:] = still

    for t in trades:
        close_due(t["entry_ts"])

        # Same-symbol same-side cooldown
        key = (t["symbol"], t["side"])
        prev = last_entry.get(key)
        if prev is not None and (t["entry_ts"] - prev).days < cooldown_days:
            skipped_cooldown += 1
            continue

        cd = t["entry_ts"].date()
        cw = t["entry_ts"].isocalendar()[1]
        cm = t["entry_ts"].month
        if cd != last_d: daily_anchor = equity; last_d = cd
        if cw != last_w: weekly_anchor = equity; last_w = cw
        if cm != last_m: monthly_anchor = equity; last_m = cm
        if blocked_until and t["entry_ts"] < blocked_until:
            skipped_breaker += 1
            continue
        if (daily_anchor - equity)/max(daily_anchor,1) >= 0.05:
            blocked_until = t["entry_ts"] + timedelta(days=1); continue
        if (weekly_anchor - equity)/max(weekly_anchor,1) >= 0.10:
            blocked_until = t["entry_ts"] + timedelta(days=7); continue
        if (monthly_anchor - equity)/max(monthly_anchor,1) >= 0.15:
            blocked_until = t["entry_ts"] + timedelta(days=30); continue
        if len(open_pos) >= max_concurrent:
            skipped_concurrent += 1
            continue

        sl_pct = abs(t["entry_price"] - t["initial_sl"])/t["entry_price"]
        if sl_pct <= 0: continue
        risk_pct = risk_fn(t["conf"])
        risk_d = equity * risk_pct
        notional = risk_d / sl_pct
        # Lev 3x (margin avantaji icin) — P&L sabit
        margin = notional / 3.0
        if margin > cash: continue
        cash -= margin
        last_entry[key] = t["entry_ts"]
        open_pos.append({"exit_ts": t["exit_ts"], "margin": margin, "risk": risk_d, "R": t["R"]})

    for p in open_pos:
        cash += p["margin"] + p["risk"] * p["R"]
        equity = cash
        Rs.append(p["R"])
        eq_curve.append(equity)

    peak = eq_curve[0]
    max_dd = 0
    for v in eq_curve:
        if v > peak: peak = v
        dd = (v - peak)/peak
        if dd < max_dd: max_dd = dd

    win = sum(1 for x in Rs if x > 0)/len(Rs) if Rs else 0
    avg_r = np.mean(Rs) if Rs else 0
    return {"final": equity, "max_dd": max_dd, "trades": len(Rs), "wr": win, "avg_r": avg_r,
            "skipped_cooldown": skipped_cooldown, "skipped_concurrent": skipped_concurrent}


def main():
    print("=" * 80)
    print("HEDEF: YILLIK %50 ROI — multi-strategy + dyn 1-4 + max_concurrent 8")
    print("=" * 80)
    print()

    all_trades = []
    for module_name, class_name in STRATEGIES_1D:
        print(f"Toplaniyor: {module_name}...")
        trs = _gather_for(module_name, class_name, tf="1d")
        print(f"  {len(trs)} sinyal")
        all_trades.extend(trs)

    # 4h engulfing
    print(f"Toplaniyor: engulfing_continuation_4h ...")
    trs_4h = _gather_for("engulfing_continuation", "EngulfingContinuationStrategy", tf="4h")
    if trs_4h:
        for t in trs_4h: t["strategy"] = "engulfing_4h"
        print(f"  {len(trs_4h)} sinyal (4h)")
        all_trades.extend(trs_4h)

    all_trades.sort(key=lambda x: x["entry_ts"])
    print(f"\nTOPLAM {len(all_trades)} sinyal\n")

    # Senaryolar
    print("=" * 100)
    print("SCENARIOS")
    print("=" * 100)

    # Top 3 (current production)
    top3 = [t for t in all_trades if t["strategy"] in ("engulfing_continuation", "pin_bar_round_numbers", "obv_engulfing_confluence")]
    # Top 5 (1d only, no 4h)
    top5_1d = [t for t in all_trades if t["tf"] == "1d"]
    # All (5 strats + 4h)
    all_combined = all_trades

    scenarios = [
        ("Top 3 (current prod) %2 sabit", top3, lambda c: 0.02, 5, 7),
        ("Top 3 dyn 1-4 max5", top3, conf_to_risk_dyn, 5, 7),
        ("Top 3 dyn 1-4 max8 cooldown3", top3, conf_to_risk_dyn, 8, 3),
        ("Top 5 1d dyn 1-4 max8", top5_1d, conf_to_risk_dyn, 8, 3),
        ("Top 5 + 4h dyn 1-4 max8", all_combined, conf_to_risk_dyn, 8, 3),
        ("Top 5 + 4h dyn 1-4 max10", all_combined, conf_to_risk_dyn, 10, 2),
    ]

    print(f"{'Senaryo':<38} {'sinyal':>7} {'final$':>10} {'5y%':>8} {'yIllIk':>8} {'maxDD':>7} {'WR':>5}")
    print("-" * 100)

    best = None
    for name, ts, fn, mc, cd in scenarios:
        if not ts: continue
        r = replay_portfolio(ts, risk_fn=fn, max_concurrent=mc, cooldown_days=cd)
        if r is None: continue
        ret = (r["final"]/10000-1)*100
        ann = ((r["final"]/10000)**(1/5)-1)*100
        line = f"{name:<38} {len(ts):>7} {r['final']:>10,.0f} {ret:>+7.1f}% {ann:>+7.2f}% {r['max_dd']*100:>+6.1f}% {r['wr']*100:>4.0f}%"
        print(line)
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
            print(f"  Yari yol — hedefe yaklasiyoruz (%30+)")
        else:
            print(f"  Hedef hala uzak — daha cok strateji veya MTF gerek")


if __name__ == "__main__":
    main()
