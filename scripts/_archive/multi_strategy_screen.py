"""Multi-strategy screener — 5y'de hangi stratejiler edge veriyor?

Her strateji icin trade'leri topla, gercek (bug-fix) replay ile yillik ROI hesapla.
En iyi 3-5 strateji portfoy adaylari.
"""
from __future__ import annotations

import io
import sys
import traceback
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


# Strateji adaylari — manifest'i olan ve test edilebilir olanlar
STRATEGY_CANDIDATES = [
    ("engulfing_continuation", "EngulfingContinuationStrategy"),
    ("pin_bar_htf_sr", "PinBarHtfSrStrategy"),
    ("ob_mitigation_strict", "OBMitigationStrictStrategy"),
    ("ii_breakout", "IIBreakoutStrategy"),
    ("brooks_failed_breakout", "BrooksFailedBreakoutStrategy"),
    ("failed_bo_bos_reclaim", "FailedBoBosReclaimStrategy"),
    ("three_methods", "ThreeMethodsStrategy"),
    ("morning_evening_star", "MorningEveningStarStrategy"),
    ("naked_poc_mr", "NakedPocMrStrategy"),
    ("pin_bar_round_numbers", "PinBarRoundNumbersStrategy"),
    ("wyckoff_phase_d", "WyckoffPhaseDStrategy"),
    ("wyckoff_spring_vsa", "WyckoffSpringVsaStrategy"),
    ("smc_orderblock", "SMCOrderBlockStrategy"),
    ("equal_highs_sweep", "EqualHighsSweepStrategy"),
    ("crows_buying_climax", "CrowsBuyingClimaxStrategy"),
    ("three_white_soldiers", "ThreeWhiteSoldiersStrategy"),
    ("three_black_crows", "ThreeBlackCrowsStrategy"),
    ("vsa_climax_test", "VsaClimaxTestStrategy"),
    ("obv_engulfing_confluence", "OBVEngulfingConfluenceStrategy"),
    ("brooks_h2_l2", "BrooksH2L2Strategy"),
]


def _load_strategy(module_name, class_name):
    """Strateji yukle, manifest ile."""
    try:
        mod = __import__(f"price_action.strategies.{module_name}", fromlist=[class_name, "_default_manifest"])
        cls = getattr(mod, class_name)
        manifest_fn = getattr(mod, "_default_manifest", None)
        if manifest_fn is None:
            return None
        return cls(manifest_fn())
    except Exception as e:
        return None


def _gather_trades(strategy):
    """Tum sembollerde trade'leri topla."""
    from price_action.backtest.engine import BacktestEngine
    from scripts.run_real_backtest import _load_symbol_ohlcv

    out = []
    for sym in SYMBOLS:
        try:
            df = _load_symbol_ohlcv(sym, tf="1d")
            if df is None or df.empty:
                continue
            df = df.sort_values("ts").reset_index(drop=True)
            df["symbol"] = sym
            df["venue"] = "binance"
            df["timeframe"] = "1d"
            def prov(*a, **k): return df.copy()
            e = BacktestEngine(risk_officer=None, store_load=None)
            r = e.run(strategy, [sym], start=df["ts"].iloc[0].to_pydatetime(),
                     end=df["ts"].iloc[-1].to_pydatetime(), timeframe="1d",
                     initial_capital=10_000.0, fees={"taker":0.00075,"maker":-0.00010},
                     slippage_bps=5.0, ohlcv_provider=prov)
            for _, t in r.trades.iterrows():
                out.append({
                    "entry_ts": t["entry_ts"],
                    "exit_ts": t["exit_ts"],
                    "entry_price": float(t["entry_price"]),
                    "initial_sl": float(t["initial_sl"]),
                    "R": float(t["realized_r_multiple"]),
                    "symbol": sym,
                    "side": str(t["side"]),
                    "confluence": float(t["confluence_score"]),
                })
        except Exception:
            continue
    out.sort(key=lambda x: x["entry_ts"])
    return out


def replay_simple(trades, risk_pct=0.02, max_concurrent=5):
    """Sade replay: sabit %2 risk, lev 1x (bug-free)."""
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
        if len(open_pos) >= max_concurrent: continue

        sl_pct = abs(t["entry_price"] - t["initial_sl"])/t["entry_price"]
        if sl_pct <= 0: continue
        risk_d = equity * risk_pct
        notional = risk_d / sl_pct
        margin = notional  # lev 1x sade
        if margin > cash: continue
        cash -= margin
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
    return {"final": equity, "max_dd": max_dd, "trades": len(Rs), "wr": win, "avg_r": avg_r}


def main():
    print("=" * 100)
    print("MULTI-STRATEGY SCREENER — 5y, 8 sembol, sabit %2 risk, bug-free formul")
    print("=" * 100)
    print()

    results = []
    print(f"{'Strateji':<32} {'sinyal':>7} {'final$':>10} {'5y%':>8} {'yillIk':>8} {'maxDD':>7} {'WR':>5} {'avgR':>6}")
    print("-" * 100)

    for module_name, class_name in STRATEGY_CANDIDATES:
        strategy = _load_strategy(module_name, class_name)
        if strategy is None:
            print(f"{module_name:<32} ! manifest yok / yuklenemedi")
            continue
        try:
            trades = _gather_trades(strategy)
            if not trades or len(trades) < 5:
                print(f"{module_name:<32} ! cok az sinyal ({len(trades)})")
                continue
            r = replay_simple(trades)
            if r is None:
                continue
            ret_5y = (r["final"]/10000-1)*100
            ann = ((r["final"]/10000)**(1/5)-1)*100
            print(f"{module_name:<32} {len(trades):>7} {r['final']:>10,.0f} {ret_5y:>+7.1f}% {ann:>+7.2f}% {r['max_dd']*100:>+6.1f}% {r['wr']*100:>4.0f}% {r['avg_r']:>+5.2f}")
            results.append({
                "name": module_name, "trades": trades, "n": len(trades),
                "final": r["final"], "ann": ann, "dd": r["max_dd"], "wr": r["wr"], "avg_r": r["avg_r"],
            })
        except Exception as e:
            print(f"{module_name:<32} ! hata: {str(e)[:50]}")
            continue

    print()
    print("=" * 100)
    print("EN IYI 5 STRATEJI (yillik ROI bazinda)")
    print("=" * 100)
    results.sort(key=lambda x: x["ann"], reverse=True)
    for i, r in enumerate(results[:8], 1):
        print(f"{i}. {r['name']:<32} yillik {r['ann']:>+6.1f}% | DD {r['dd']*100:>+5.1f}% | WR {r['wr']*100:.0f}% | {r['n']} sinyal")

    # PORTFOY: en iyi 4 stratejinin trade'lerini birlestir
    print()
    print("=" * 100)
    print("PORTFOY: EN IYI 4 STRATEJI BIRLESTIR")
    print("=" * 100)
    top4 = results[:4]
    if len(top4) >= 2:
        all_trades = []
        for r in top4:
            for t in r["trades"]:
                t2 = dict(t)
                t2["strategy"] = r["name"]
                all_trades.append(t2)
        all_trades.sort(key=lambda x: x["entry_ts"])
        print(f"\nToplam {len(all_trades)} sinyal ({len(top4)} strateji birlesik)")

        port = replay_simple(all_trades, risk_pct=0.015)  # %1.5 daha guvenli (cok sinyal)
        if port:
            ret = (port["final"]/10000-1)*100
            ann = ((port["final"]/10000)**(1/5)-1)*100
            print(f"\nPORTFOY (4 strateji, %1.5 risk):")
            print(f"  Final: ${port['final']:,.0f}")
            print(f"  5y getiri: {ret:+.1f}%")
            print(f"  Yillik: {ann:+.2f}%")
            print(f"  maxDD: {port['max_dd']*100:+.1f}%")
            print(f"  WR: {port['wr']*100:.0f}%")
            print(f"  avg R: {port['avg_r']:+.2f}")


if __name__ == "__main__":
    main()
