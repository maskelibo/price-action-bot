"""Multi-strategy portfolio (3 strateji + dynamic risk + same-symbol cooldown).

Top 3 strateji:
  1. engulfing_continuation   yillik +9.6%
  2. pin_bar_round_numbers     yillik +7.1%
  3. obv_engulfing_confluence  yillik +4.9%

PORTFOY ozellikleri:
  - Dynamic risk %1-%4 (confidence-based)
  - Same-symbol same-side 7-day cooldown (cifte pozisyon engelle)
  - max_concurrent 5
  - Drawdown breakers 5/10/15
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


TOP3 = [
    ("engulfing_continuation", "EngulfingContinuationStrategy"),
    ("pin_bar_round_numbers", "PinBarRoundNumbersStrategy"),
    ("obv_engulfing_confluence", "OBVEngulfingConfluenceStrategy"),
]


def _gather_for(module_name, class_name):
    from price_action.backtest.engine import BacktestEngine
    from scripts.run_real_backtest import _load_symbol_ohlcv

    mod = __import__(f"price_action.strategies.{module_name}", fromlist=[class_name, "_default_manifest"])
    cls = getattr(mod, class_name)
    manifest_fn = getattr(mod, "_default_manifest")
    s = cls(manifest_fn())

    out = []
    for sym in SYMBOLS:
        try:
            df = _load_symbol_ohlcv(sym, tf="1d")
            if df is None or df.empty: continue
            df = df.sort_values("ts").reset_index(drop=True)
            df["symbol"] = sym
            df["venue"] = "binance"
            df["timeframe"] = "1d"
            def prov(*a, **k): return df.copy()
            e = BacktestEngine(risk_officer=None, store_load=None)
            r = e.run(s, [sym], start=df["ts"].iloc[0].to_pydatetime(),
                     end=df["ts"].iloc[-1].to_pydatetime(), timeframe="1d",
                     initial_capital=10_000.0, fees={"taker":0.00075,"maker":-0.00010},
                     slippage_bps=5.0, ohlcv_provider=prov)
            for _, t in r.trades.iterrows():
                # Confidence proxy
                conf = max(0.0, min(1.0, (float(t["confluence_score"]) - 1.5) / 1.5))
                out.append({
                    "entry_ts": pd.Timestamp(t["entry_ts"]).tz_localize("UTC") if pd.Timestamp(t["entry_ts"]).tzinfo is None else pd.Timestamp(t["entry_ts"]),
                    "exit_ts": pd.Timestamp(t["exit_ts"]).tz_localize("UTC") if pd.Timestamp(t["exit_ts"]).tzinfo is None else pd.Timestamp(t["exit_ts"]),
                    "entry_price": float(t["entry_price"]),
                    "initial_sl": float(t["initial_sl"]),
                    "R": float(t["realized_r_multiple"]),
                    "symbol": sym,
                    "side": str(t["side"]),
                    "conf": conf,
                    "strategy": module_name,
                })
        except Exception as e:
            print(f"  ! {module_name} on {sym}: {e}")
            continue
    return out


def conf_to_risk_dyn(conf: float) -> float:
    if conf < 0.32: return 0.010
    if conf < 0.42: return 0.015
    if conf < 0.52: return 0.020
    if conf < 0.58: return 0.030
    return 0.040


def conf_to_risk_static(conf: float) -> float:
    return 0.020  # sabit %2


def replay_portfolio(trades, risk_fn=None, max_concurrent=5, cooldown_days=7):
    if risk_fn is None:
        risk_fn = conf_to_risk_dyn
    """Portfoy replay: dynamic risk + same-symbol same-side cooldown."""
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

    # Same-symbol same-side last entry tracking
    last_entry: dict[tuple, pd.Timestamp] = {}
    skipped_cooldown = 0
    skipped_concurrent = 0

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
        if blocked_until and t["entry_ts"] < blocked_until: continue
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
        margin = notional  # lev 1x
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
    print("MULTI-STRATEGY PORTFOLIO (3 strateji + dyn risk + cooldown)")
    print("=" * 80)
    print()

    # Topla
    all_trades = []
    for module_name, class_name in TOP3:
        print(f"Toplaniyor: {module_name}...")
        trs = _gather_for(module_name, class_name)
        print(f"  {len(trs)} sinyal")
        all_trades.extend(trs)

    all_trades.sort(key=lambda x: x["entry_ts"])
    print(f"\nToplam birlestik: {len(all_trades)} sinyal\n")

    # Senaryolar
    print("=" * 80)
    print("PORTFOY SCENARIOS")
    print("=" * 80)

    engulf_only = [t for t in all_trades if t["strategy"] == "engulfing_continuation"]

    scenarios = [
        ("Solo engulfing (sabit %2)",  engulf_only,  conf_to_risk_static),
        ("Solo engulfing (dyn 1-4)",   engulf_only,  conf_to_risk_dyn),
        ("Multi 3-strat (sabit %2)",   all_trades,   conf_to_risk_static),
        ("Multi 3-strat (dyn 1-4)",    all_trades,   conf_to_risk_dyn),
        ("Multi 3-strat (sabit %1)",   all_trades,   lambda c: 0.01),
        ("Multi 3-strat (sabit %1.5)", all_trades,   lambda c: 0.015),
    ]

    print(f"{'Senaryo':<32} {'sinyal':>7} {'final$':>10} {'5y%':>8} {'yIllIk':>8} {'maxDD':>7} {'WR':>5} {'skip':>5}")
    print("-" * 95)

    for name, ts, risk_fn in scenarios:
        if not ts: continue
        r = replay_portfolio(ts, risk_fn=risk_fn)
        if r is None: continue
        ret = (r["final"]/10000-1)*100
        ann = ((r["final"]/10000)**(1/5)-1)*100
        print(f"{name:<32} {len(ts):>7} {r['final']:>10,.0f} {ret:>+7.1f}% {ann:>+7.2f}% {r['max_dd']*100:>+6.1f}% {r['wr']*100:>4.0f}% {r['skipped_cooldown']:>5}")


if __name__ == "__main__":
    main()
